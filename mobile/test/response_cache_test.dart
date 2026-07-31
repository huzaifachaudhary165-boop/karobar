
import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/network/api_client.dart';
import 'package:karobar/core/storage/token_store.dart';
import 'package:karobar/data/local/app_database.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The saved copy of a screen.
///
/// Two separate promises are made to the shopkeeper here, and they fail
/// differently. The first is that a screen paints immediately from what was
/// last seen instead of showing a spinner. The second is that when the signal
/// drops, yesterday's figures are still there rather than an error page.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late AppDatabase db;
  late TokenStore store;
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
          default:
            return null;
        }
      },
    );

    // A business id is what scopes the cache. Without one nothing is cached at
    // all, so this is not incidental setup.
    SharedPreferences.setMockInitialValues({'karobar.business_id': 'biz-1'});
    store = TokenStore(await SharedPreferences.getInstance());
    await store.saveTokens(access: 'access', refresh: 'refresh');
    db = AppDatabase.memory();
  });

  tearDown(() async => db.close());

  ApiClient clientReturning(Future<ResponseBody> Function(int call) responder) {
    var calls = 0;
    return ApiClient(store, cache: db)
      ..adapters = _Adapter((_) async => responder(++calls));
  }

  test('a good response is saved', () async {
    final client = clientReturning((_) async => _json(200, '{"items":["sugar"]}'));

    await client.get('/items');
    // The write is fire-and-forget so a slow disk never delays a read.
    await Future<void>.delayed(const Duration(milliseconds: 60));

    final saved = await db.cached('/items', 'biz-1');
    expect(saved, isNotNull, reason: 'nothing was cached');
    expect((saved!.body as Map)['items'], ['sugar']);
    client.dispose();
  });

  test('the saved copy is handed over before the request is even sent', () async {
    await db.cacheResponse('/items', 'biz-1', {'items': ['old sugar']});

    final client = clientReturning((_) async {
      await Future<void>.delayed(const Duration(milliseconds: 120));
      return _json(200, '{"items":["fresh sugar"]}');
    });

    final order = <String>[];
    final fresh = await client.get(
      '/items',
      onCached: (body) => order.add('cached:${(body as Map)['items'][0]}'),
    );
    order.add('fresh:${(fresh as Map)['items'][0]}');

    expect(order, ['cached:old sugar', 'fresh:fresh sugar'],
        reason: 'the screen must paint from disk first, then update');
    client.dispose();
  });

  test('when the phone is offline the saved copy answers', () async {
    await db.cacheResponse('/items', 'biz-1', {'items': ['sugar']});

    final client = ApiClient(store, cache: db)
      ..adapters = _Adapter((options) async => throw DioException.connectionError(
            requestOptions: options,
            reason: 'no route to host',
          ));

    final result = await client.get('/items');

    expect((result as Map)['items'], ['sugar']);
    expect(client.servedFromCache, isTrue, reason: 'the banner reads this');
    client.dispose();
  });

  test('a failed renewal is offline enough to fall back to the cache', () async {
    // The session having gone stale must not take the saved figures with it.
    // A 401 whose renewal times out surfaces as a connection error precisely so
    // this fallback applies.
    await db.cacheResponse('/items', 'biz-1', {'items': ['sugar']});

    final client = ApiClient(store, cache: db)
      ..adapters = _Adapter((options) async {
        if (options.path.contains('/auth/refresh')) {
          throw DioException.connectionTimeout(
            timeout: const Duration(seconds: 5),
            requestOptions: options,
          );
        }
        return _json(401, '{}');
      });

    final result = await client.get('/items');

    expect((result as Map)['items'], ['sugar']);
    expect(client.servedFromCache, isTrue);
    client.dispose();
  });

  test('one shop never sees another shop cached data', () async {
    await db.cacheResponse('/items', 'other-shop', {'items': ['not yours']});

    final client = ApiClient(store, cache: db)
      ..adapters = _Adapter((options) async => throw DioException.connectionError(
            requestOptions: options,
            reason: 'offline',
          ));

    await expectLater(client.get('/items'), throwsA(isA<Object>()));
    client.dispose();
  });

  test('the same query in a different order hits the same saved copy', () async {
    final client = clientReturning((_) async => _json(200, '{"items":[]}'));

    await client.get('/items', query: {'page': 1, 'size': 25});
    await Future<void>.delayed(const Duration(milliseconds: 60));

    var handed = false;
    await client.get(
      '/items',
      query: {'size': 25, 'page': 1},
      onCached: (_) => handed = true,
    );

    expect(handed, isTrue, reason: 'query key order must not split the cache');
    client.dispose();
  });

  test('an offline read with nothing saved reports the connection problem',
      () async {
    final client = ApiClient(store, cache: db)
      ..adapters = _Adapter((options) async => throw DioException.connectionError(
            requestOptions: options,
            reason: 'offline',
          ));

    await expectLater(client.get('/items'), throwsA(predicate((e) {
      return (e as dynamic).isOffline == true;
    })));
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

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);

  final Future<ResponseBody> Function(RequestOptions options) handler;

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? stream,
          Future<void>? cancelFuture) =>
      handler(options);

  @override
  void close({bool force = false}) {}
}
