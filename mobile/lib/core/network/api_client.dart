import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kDebugMode, debugPrint, visibleForTesting;

import '../../data/local/app_database.dart';
import '../config/env.dart';
import '../storage/token_store.dart';
import '../utils/mime.dart';
import 'api_exception.dart';

/// What happened when the app tried to renew an expired access token.
///
/// Kept as three cases rather than a bool because "the server rejected the
/// refresh token" and "we could not reach the server" look identical to a
/// caller that only sees false — and treating the second as the first signs
/// people out for having bad signal.
enum RefreshOutcome {
  /// A new access token is stored and the request can be replayed.
  renewed,

  /// The server saw the refresh token and refused it. The session is over.
  rejected,

  /// No verdict: a timeout, no route, or a server error. The tokens are kept.
  unreachable,
}

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
      InterceptorsWrapper(onRequest: _onRequest, onResponse: _onResponse),
    );

    if (kDebugMode) {
      _dio.interceptors.add(
        LogInterceptor(requestBody: true, responseBody: false, logPrint: _log),
      );
    }

    // Renewal goes out on its own client, deliberately without the interceptors
    // above — a 401 on the renewal must not trigger another renewal. It is a
    // field rather than a local so a test can swap its adapter; the branch it
    // guards is the one that decides whether someone stays signed in.
    _refreshDio = Dio(
      BaseOptions(
        baseUrl: Env.apiBaseUrl,
        // Without these Dio waits on the OS default, which on a stalled
        // connection is minutes, with the user watching a spinner throughout.
        connectTimeout: Env.connectTimeout,
        receiveTimeout: Env.connectTimeout,
        validateStatus: (status) => status != null && status < 500,
      ),
    );
  }

  final TokenStore _store;

  /// Optional read-through cache. Null in tests and before the database is
  /// opened; every call site degrades to plain network behaviour.
  final AppDatabase? _cache;

  late final Dio _dio;
  late final Dio _refreshDio;

  /// Test seam: lets a test drive both clients without a network.
  @visibleForTesting
  set adapters(HttpClientAdapter adapter) {
    _dio.httpClientAdapter = adapter;
    _refreshDio.httpClientAdapter = adapter;
  }

  /// True when the most recent [get] was answered from disk instead of the
  /// network. The offline banner reads this to say "showing saved data".
  bool servedFromCache = false;

  /// Fires when the refresh token is also dead and the user must sign in again.
  final _sessionExpired = StreamController<void>.broadcast();
  Stream<void> get onSessionExpired => _sessionExpired.stream;

  Completer<RefreshOutcome>? _refreshing;

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
      'file': MultipartFile.fromBytes(
        bytes,
        filename: filename,
        // Without this Dio declares application/octet-stream, and the server
        // refuses it as an unsupported file type — so every photo picked from
        // the gallery and every picture taken with the camera failed to upload,
        // whatever it actually was.
        contentType: DioMediaType.parse(contentType ?? mimeTypeFor(filename)),
      ),
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

  /// Renewal lives here, not in `onError`, and that placement is load-bearing.
  ///
  /// `validateStatus` lets everything under 500 through, so a 401 arrives as an
  /// ordinary response rather than an exception — this callback is the only
  /// place the app ever sees it. `handler.reject()` does **not** re-enter the
  /// same interceptor's `onError`; Dio passes it further down the chain. So the
  /// renewal code that used to live in `onError` never ran for an expired
  /// token, not once.
  ///
  /// The access token lasts an hour. Every session therefore ended after an
  /// hour and stayed ended: reopening the app showed "session expired" on every
  /// screen, and the refresh button only produced another 401. `test/
  /// dio_reject_probe_test.dart` pins the Dio behaviour this depends on.
  Future<void> _onResponse(
    Response<dynamic> response,
    ResponseInterceptorHandler handler,
  ) async {
    final status = response.statusCode ?? 0;
    if (status < 400) {
      handler.next(response);
      return;
    }

    final options = response.requestOptions;
    final canRenew = status == 401 &&
        !options.path.contains('/auth/refresh') &&
        options.extra['retried'] != true;

    if (canRenew) {
      switch (await _refreshToken()) {
        case RefreshOutcome.renewed:
          try {
            options.extra['retried'] = true;
            options.headers['Authorization'] = 'Bearer ${await _store.accessToken}';
            handler.resolve(await _dio.fetch<dynamic>(options));
          } on DioException catch (retryError) {
            handler.reject(retryError);
          }
          return;

        case RefreshOutcome.rejected:
          // The server looked at the refresh token and said no. That is the
          // only thing that ends a session.
          _sessionExpired.add(null);

        case RefreshOutcome.unreachable:
          // No verdict, so the session may well be fine. Surface it as a
          // connection problem — which is what makes the read path fall back to
          // the saved copy instead of showing an error screen.
          handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.connectionError,
              message: 'Could not reach the server to renew the session.',
            ),
          );
          return;
      }
    }

    handler.reject(
      DioException(
        requestOptions: options,
        response: response,
        type: DioExceptionType.badResponse,
      ),
    );
  }

  /// Concurrent 401s share one refresh instead of racing each other.
  ///
  /// The distinction between [RefreshOutcome.rejected] and
  /// [RefreshOutcome.unreachable] is the whole point of this method.
  ///
  /// This used to catch everything and wipe the tokens, so *any* failure signed
  /// the user out for good — a timeout, a cold start, one bar of signal. The
  /// access token only lasts an hour, so reopening the app the next morning on
  /// a weak connection was enough: the renewal timed out, the tokens were
  /// deleted, and every screen said the session had expired. The saved data was
  /// still on the phone and now unreachable, and the refresh button could not
  /// help because there was nothing left to refresh with.
  ///
  /// A refresh token is good for sixty days. Throwing it away because one
  /// request did not complete is never the right call.
  Future<RefreshOutcome> _refreshToken() async {
    if (_refreshing != null) return _refreshing!.future;

    final completer = Completer<RefreshOutcome>();
    _refreshing = completer;

    Future<RefreshOutcome> finish(RefreshOutcome outcome) async {
      completer.complete(outcome);
      return outcome;
    }

    try {
      final refresh = await _store.refreshToken;
      if (refresh == null) return await finish(RefreshOutcome.rejected);

      final response = await _refreshDio.post<dynamic>(
        '/auth/refresh',
        data: {'refresh_token': refresh},
      );

      final status = response.statusCode ?? 0;
      if (status == 401 || status == 403) {
        // Genuinely spent or revoked. Now clearing is correct.
        await _store.clearTokens();
        return await finish(RefreshOutcome.rejected);
      }
      if (status >= 400) {
        // A 4xx that is not about the token — keep the session.
        return await finish(RefreshOutcome.unreachable);
      }

      final tokens = (response.data as Map)['tokens'] as Map;
      await _store.saveTokens(
        access: tokens['access_token'] as String,
        refresh: tokens['refresh_token'] as String,
      );
      return await finish(RefreshOutcome.renewed);
    } on DioException {
      // Timeout, no route, DNS, a 5xx — the server never gave a verdict.
      return await finish(RefreshOutcome.unreachable);
    } catch (_) {
      // A malformed body. Also not evidence the session is over.
      return await finish(RefreshOutcome.unreachable);
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
