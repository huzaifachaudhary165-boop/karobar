import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/network/api_client.dart';
import 'package:karobar/core/storage/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Renewing an expired access token.
///
/// The access token lasts an hour; the refresh token lasts sixty days. So
/// reopening the app the next morning always goes through this path, and what
/// it does when the request does not complete decides whether the shopkeeper is
/// still signed in.
///
/// It used to catch every failure and delete both tokens. One timeout, one cold
/// start, one bar of signal, and the session was gone for good — every screen
/// said it had expired, the saved data on the phone became unreachable, and the
/// refresh button had nothing left to refresh with.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late TokenStore store;

  /// flutter_secure_storage talks to the OS keystore over a platform channel,
  /// which does not exist in a test. A map stands in for it, so the tokens
  /// really are written and read back rather than being assumed.
  final keystore = <String, String>{};

  setUp(() async {
    keystore.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),
      (call) async {
        final args = Map<String, dynamic>.from(call.arguments as Map? ?? {});
        final key = args['key'] as String?;
        switch (call.method) {
          case 'write':
            keystore[key!] = args['value'] as String;
            return null;
          case 'read':
            return keystore[key];
          case 'delete':
            keystore.remove(key);
            return null;
          case 'deleteAll':
            keystore.clear();
            return null;
          case 'readAll':
            return keystore;
          case 'containsKey':
            return keystore.containsKey(key);
          default:
            return null;
        }
      },
    );

    SharedPreferences.setMockInitialValues({});
    store = TokenStore(await SharedPreferences.getInstance());
    await store.saveTokens(access: 'old-access', refresh: 'good-refresh');
  });

  /// Answers `/auth/refresh` with [refresh] and everything else with [other].
  HttpClientAdapter adapter({
    required Future<ResponseBody> Function() refresh,
    Future<ResponseBody> Function()? other,
  }) =>
      _FakeAdapter((options) async {
        if (options.path.contains('/auth/refresh')) return refresh();
        return (other ?? () async => _json(200, '{"ok":true}'))();
      });

  group('when the server rejects the refresh token', () {
    test('the session ends and the tokens are cleared', () async {
      final client = ApiClient(store)
        ..adapters = adapter(
          refresh: () async => _json(401, '{"error":{"code":"unauthenticated"}}'),
          other: () async => _json(401, '{"error":{"code":"unauthenticated"}}'),
        );

      final expired = client.onSessionExpired.first
          .timeout(const Duration(seconds: 5), onTimeout: () => throw StateError('no signal'));

      await expectLater(client.get('/items'), throwsA(isA<Object>()));
      await expired;

      expect(await store.accessToken, isNull, reason: 'a refused token is worth clearing');
      expect(await store.refreshToken, isNull);
      client.dispose();
    });
  });

  group('when the server cannot be reached', () {
    test('a timeout does NOT sign the user out', () async {
      // The reported bug, in one test.
      final client = ApiClient(store)
        ..adapters = adapter(
          refresh: () async => throw DioException.connectionTimeout(
            timeout: const Duration(seconds: 5),
            requestOptions: RequestOptions(path: '/auth/refresh'),
          ),
          other: () async => _json(401, '{"error":{"code":"unauthenticated"}}'),
        );

      var sessionEnded = false;
      final sub = client.onSessionExpired.listen((_) => sessionEnded = true);

      await expectLater(client.get('/items'), throwsA(isA<Object>()));
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(sessionEnded, isFalse, reason: 'a timeout is not a verdict on the session');
      expect(await store.refreshToken, 'good-refresh',
          reason: 'sixty days of validity must not be thrown away over one timeout');

      await sub.cancel();
      client.dispose();
    });

    test('a 500 from the server does not sign the user out either', () async {
      final client = ApiClient(store)
        ..adapters = adapter(
          refresh: () async => throw DioException.badResponse(
            statusCode: 500,
            requestOptions: RequestOptions(path: '/auth/refresh'),
            response: Response(
              requestOptions: RequestOptions(path: '/auth/refresh'),
              statusCode: 500,
            ),
          ),
          other: () async => _json(401, '{}'),
        );

      var sessionEnded = false;
      final sub = client.onSessionExpired.listen((_) => sessionEnded = true);

      await expectLater(client.get('/items'), throwsA(isA<Object>()));
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(sessionEnded, isFalse);
      expect(await store.refreshToken, 'good-refresh');

      await sub.cancel();
      client.dispose();
    });

    test('the failure is reported as a connection problem, so the cache answers',
        () async {
      // `get` only falls back to the saved copy when the error looks offline.
      // If renewal failure surfaced as anything else, a user with no signal
      // would get an error screen instead of yesterday's figures.
      final client = ApiClient(store)
        ..adapters = adapter(
          refresh: () async => throw DioException.connectionTimeout(
            timeout: const Duration(seconds: 5),
            requestOptions: RequestOptions(path: '/auth/refresh'),
          ),
          other: () async => _json(401, '{}'),
        );

      try {
        await client.get('/items');
        fail('expected the request to fail');
      } catch (error) {
        expect(
          (error as dynamic).isOffline,
          isTrue,
          reason: 'must be treated as offline so the cached copy is used',
        );
      }
      client.dispose();
    });
  });

  group('when renewal succeeds', () {
    test('the new tokens are stored and the request is replayed', () async {
      var refreshCalls = 0;
      var itemCalls = 0;

      final client = ApiClient(store)
        ..adapters = _FakeAdapter((options) async {
          if (options.path.contains('/auth/refresh')) {
            refreshCalls += 1;
            return _json(200,
                '{"tokens":{"access_token":"new-access","refresh_token":"new-refresh"}}');
          }
          itemCalls += 1;
          // 401 first, then success once the token has been renewed.
          return itemCalls == 1 ? _json(401, '{}') : _json(200, '{"items":[]}');
        });

      final result = await client.get('/items');

      expect(result, isNotNull);
      expect(refreshCalls, 1);
      expect(itemCalls, 2, reason: 'the original request must be replayed');
      expect(await store.accessToken, 'new-access');
      expect(await store.refreshToken, 'new-refresh');
      client.dispose();
    });

    test('several requests failing at once share a single renewal', () async {
      // Reopening the app fires the dashboard, items, parties and invoices at
      // the same moment. Renewing per request would spend the rotating refresh
      // token several times over and destroy the session.
      var refreshCalls = 0;

      final client = ApiClient(store)
        ..adapters = _FakeAdapter((options) async {
          if (options.path.contains('/auth/refresh')) {
            refreshCalls += 1;
            await Future<void>.delayed(const Duration(milliseconds: 30));
            return _json(200,
                '{"tokens":{"access_token":"new-access","refresh_token":"new-refresh"}}');
          }
          return options.headers['Authorization'] == 'Bearer new-access'
              ? _json(200, '{"items":[]}')
              : _json(401, '{}');
        });

      await Future.wait([
        client.get('/items'),
        client.get('/parties'),
        client.get('/vouchers'),
        client.get('/reports/dashboard'),
      ]);

      expect(refreshCalls, 1,
          reason: 'a rotating refresh token may only be spent once');
      client.dispose();
    });
  });

  test('a 401 on the renewal itself does not loop', () async {
    var refreshCalls = 0;
    final client = ApiClient(store)
      ..adapters = _FakeAdapter((options) async {
        if (options.path.contains('/auth/refresh')) {
          refreshCalls += 1;
          return _json(401, '{}');
        }
        return _json(401, '{}');
      });

    await expectLater(client.get('/items'), throwsA(isA<Object>()));
    expect(refreshCalls, 1);
    client.dispose();
  });
}

ResponseBody _json(int status, String body) => ResponseBody.fromString(
      body,
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final Future<ResponseBody> Function(RequestOptions options) handler;

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream,
          Future<void>? cancelFuture) =>
      handler(options);

  @override
  void close({bool force = false}) {}
}
