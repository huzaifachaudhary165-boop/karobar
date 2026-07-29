import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../data/local/app_database.dart';
import '../config/env.dart';
import '../storage/token_store.dart';
import 'api_exception.dart';

/// The single HTTP entry point.
///
/// Attaches auth and tenant headers, refreshes an expired access token once and
/// replays the original request, and turns every failure into an [ApiException].
class ApiClient {
  ApiClient(this._store, {AppDatabase? cache}) : _cache = cache {
    _dio = Dio(
      BaseOptions(
        baseUrl: Env.apiBaseUrl,
        connectTimeout: Env.connectTimeout,
        receiveTimeout: Env.receiveTimeout,
        headers: {'Accept': 'application/json'},
        // We translate status codes ourselves, so let everything through.
        validateStatus: (status) => status != null && status < 500,
      ),
    );

    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: _onRequest,
        onResponse: _onResponse,
        onError: _onError,
      ),
    );

    if (kDebugMode) {
      _dio.interceptors.add(
        LogInterceptor(requestBody: true, responseBody: false, logPrint: _log),
      );
    }
  }

  final TokenStore _store;

  /// Optional read-through cache. Null in tests and before the database is
  /// opened; every call site degrades to plain network behaviour.
  final AppDatabase? _cache;

  late final Dio _dio;

  /// True when the most recent [get] was answered from disk instead of the
  /// network. The offline banner reads this to say "showing saved data".
  bool servedFromCache = false;

  /// Fires when the refresh token is also dead and the user must sign in again.
  final _sessionExpired = StreamController<void>.broadcast();
  Stream<void> get onSessionExpired => _sessionExpired.stream;

  Completer<bool>? _refreshing;

  // ── verbs ──────────────────────────────────────────────────────

  /// Reads go through a write-through cache: a good response is saved, and a
  /// response that fails only because the phone has no signal falls back to the
  /// last saved copy rather than showing an error screen.
  ///
  /// [onCached] is what makes screens feel instant. When the last saved copy is
  /// on disk it is handed over straight away — before the request is even sent
  /// — so a list paints from local storage while the network round trip happens
  /// behind it. On a 300 ms link that is the difference between a spinner and
  /// no spinner.
  Future<dynamic> get(
    String path, {
    Map<String, dynamic>? query,
    bool cache = true,
    void Function(dynamic cachedBody)? onCached,
  }) async {
    final cleaned = _clean(query);
    final businessId = _store.businessId;
    final key = _cacheKey(path, cleaned);
    final canCache = cache && _cache != null && businessId != null;

    if (canCache && onCached != null) {
      final saved = await _cache.cached(key, businessId);
      if (saved != null) onCached(saved.body);
    }

    try {
      final data = await _send(() => _dio.get<dynamic>(path, queryParameters: cleaned));
      servedFromCache = false;
      if (canCache) {
        // Fire and forget — a cache write must never slow down or break a read.
        unawaited(_cache.cacheResponse(key, businessId, data).catchError((_) {}));
      }
      return data;
    } on ApiException catch (error) {
      if (!error.isOffline || !canCache) rethrow;

      final saved = await _cache.cached(key, businessId);
      if (saved == null) rethrow;

      servedFromCache = true;
      return saved.body;
    }
  }

  /// The last saved response for a GET, without touching the network.
  Future<dynamic> cachedBody(String path, {Map<String, dynamic>? query}) async {
    final businessId = _store.businessId;
    if (_cache == null || businessId == null) return null;
    final saved = await _cache.cached(_cacheKey(path, _clean(query)), businessId);
    return saved?.body;
  }

  Future<dynamic> post(String path, {Object? body, Map<String, dynamic>? query, Duration? timeout}) =>
      _send(() => _dio.post<dynamic>(
            path,
            data: body,
            queryParameters: _clean(query),
            options: timeout == null ? null : Options(receiveTimeout: timeout),
          ));

  Future<dynamic> patch(String path, {Object? body}) =>
      _send(() => _dio.patch<dynamic>(path, data: body));

  Future<dynamic> delete(String path, {Object? body}) =>
      _send(() => _dio.delete<dynamic>(path, data: body));

  Future<Response<dynamic>> raw(String path, {Map<String, dynamic>? query}) async {
    try {
      return await _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        options: Options(responseType: ResponseType.plain),
      );
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }

  Future<dynamic> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? contentType,
    Map<String, dynamic> fields = const {},
  }) async {
    final form = FormData.fromMap({
      ...fields,
      'file': MultipartFile.fromBytes(bytes, filename: filename),
    });
    return _send(() => _dio.post<dynamic>(path, data: form));
  }

  // ── plumbing ───────────────────────────────────────────────────
  Future<dynamic> _send(Future<Response<dynamic>> Function() call) async {
    try {
      final response = await call();
      return response.data;
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    }
  }

  Future<void> _onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await _store.accessToken;
    if (token != null) options.headers['Authorization'] = 'Bearer $token';

    final businessId = _store.businessId;
    if (businessId != null) options.headers['X-Business-Id'] = businessId;

    options.headers['X-Device-Id'] = await _store.deviceId();
    options.headers['X-App-Version'] = Env.version;
    handler.next(options);
  }

  void _onResponse(Response<dynamic> response, ResponseInterceptorHandler handler) {
    final status = response.statusCode ?? 0;
    if (status >= 400) {
      handler.reject(
        DioException(
          requestOptions: response.requestOptions,
          response: response,
          type: DioExceptionType.badResponse,
        ),
      );
      return;
    }
    handler.next(response);
  }

  Future<void> _onError(DioException error, ErrorInterceptorHandler handler) async {
    final isAuthError = error.response?.statusCode == 401;
    final isRefreshCall = error.requestOptions.path.contains('/auth/refresh');
    final alreadyRetried = error.requestOptions.extra['retried'] == true;

    if (!isAuthError || isRefreshCall || alreadyRetried) {
      handler.next(error);
      return;
    }

    final refreshed = await _refreshToken();
    if (!refreshed) {
      _sessionExpired.add(null);
      handler.next(error);
      return;
    }

    try {
      final options = error.requestOptions..extra['retried'] = true;
      options.headers['Authorization'] = 'Bearer ${await _store.accessToken}';
      handler.resolve(await _dio.fetch<dynamic>(options));
    } on DioException catch (retryError) {
      handler.next(retryError);
    }
  }

  /// Concurrent 401s share one refresh instead of racing each other.
  Future<bool> _refreshToken() async {
    if (_refreshing != null) return _refreshing!.future;

    final completer = Completer<bool>();
    _refreshing = completer;

    try {
      final refresh = await _store.refreshToken;
      if (refresh == null) {
        completer.complete(false);
        return false;
      }

      final response = await Dio(BaseOptions(baseUrl: Env.apiBaseUrl)).post<dynamic>(
        '/auth/refresh',
        data: {'refresh_token': refresh},
      );

      final tokens = (response.data as Map)['tokens'] as Map;
      await _store.saveTokens(
        access: tokens['access_token'] as String,
        refresh: tokens['refresh_token'] as String,
      );
      completer.complete(true);
      return true;
    } catch (_) {
      await _store.clearTokens();
      completer.complete(false);
      return false;
    } finally {
      _refreshing = null;
    }
  }

  /// Query keys are sorted so `?page=1&size=20` and `?size=20&page=1` hit the
  /// same cache row.
  String _cacheKey(String path, Map<String, dynamic>? query) {
    if (query == null || query.isEmpty) return path;
    final keys = query.keys.toList()..sort();
    return '$path?${keys.map((k) => '$k=${query[k]}').join('&')}';
  }

  Map<String, dynamic>? _clean(Map<String, dynamic>? query) {
    if (query == null) return null;
    final cleaned = <String, dynamic>{};
    query.forEach((key, value) {
      if (value != null && value != '') cleaned[key] = value;
    });
    return cleaned.isEmpty ? null : cleaned;
  }

  void _log(Object object) {
    if (kDebugMode) debugPrint('[api] $object');
  }

  void dispose() {
    _sessionExpired.close();
    _dio.close();
  }
}
