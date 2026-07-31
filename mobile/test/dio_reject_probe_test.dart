import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

/// Pins the Dio behaviour that decides where token renewal has to live.
///
/// `ApiClient` sets `validateStatus` to let everything under 500 through, so a
/// 401 arrives as an ordinary response and `onResponse` is the only place it is
/// ever seen. The renewal code used to sit in `onError` and be reached by
/// calling `handler.reject()` from `onResponse` — which does not work: Dio
/// passes a rejection *past* the interceptor that raised it, so that
/// interceptor's own `onError` never runs.
///
/// The cost of that was total. Access tokens last an hour, so every session
/// died after an hour and could not be renewed: reopening the app showed
/// "session expired" on every screen, and the refresh button just produced
/// another 401.
///
/// If a future Dio changes this, renewal could move back to `onError` — and
/// this test failing is how anyone would find out.
void main() {
  test('reject from onResponse does NOT reach the same interceptor onError', () async {
    var onResponseRan = false;
    var onErrorRan = false;

    final dio = Dio(BaseOptions(
      baseUrl: 'http://test.local',
      validateStatus: (s) => s != null && s < 500,
    ))
      ..httpClientAdapter = _Adapter();

    dio.interceptors.add(InterceptorsWrapper(
      onResponse: (response, handler) {
        onResponseRan = true;
        handler.reject(DioException(
          requestOptions: response.requestOptions,
          response: response,
          type: DioExceptionType.badResponse,
        ));
      },
      onError: (error, handler) {
        onErrorRan = true;
        handler.next(error);
      },
    ));

    await expectLater(dio.get<dynamic>('/anything'), throwsA(isA<DioException>()));

    expect(onResponseRan, isTrue);
    expect(
      onErrorRan,
      isFalse,
      reason: 'renewal must stay in onResponse, where the 401 is actually seen',
    );
  });

  test('a 401 arrives as a response, not an exception, under this validateStatus',
      () async {
    final dio = Dio(BaseOptions(
      baseUrl: 'http://test.local',
      validateStatus: (s) => s != null && s < 500,
    ))
      ..httpClientAdapter = _Adapter();

    final response = await dio.get<dynamic>('/anything');
    expect(response.statusCode, 401);
  });
}

class _Adapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? stream,
          Future<void>? cancelFuture) async =>
      ResponseBody.fromString('{"error":"unauthenticated"}', 401, headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      });

  @override
  void close({bool force = false}) {}
}
