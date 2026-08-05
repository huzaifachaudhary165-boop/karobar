import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/network/api_client.dart';
import 'package:karobar/core/storage/token_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// What happens when the OS keystore cannot be read.
///
/// This is not hypothetical on Android: clearing an app's data or reinstalling
/// it can leave the encrypted preferences file in place while the keystore
/// entry that decrypts it is gone, and the plugin then throws on every read.
///
/// Letting that escape an interceptor turns it into a DioException of type
/// `unknown` with no response — which the app could only describe as "something
/// went wrong". Including on the sign-in that would have repaired the state, so
/// the app becomes unusable and says nothing about why.
///
/// Not being able to attach a token is not a reason to abandon a request.
/// Signing in does not need one, and anything else gets a 401 it knows how to
/// handle.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late TokenStore store;
  var reads = 0;

  /// A keystore that fails the way a real one does after a data wipe.
  void mockBrokenKeystore() {
    reads = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),
      (call) async {
        if (call.method == 'read') {
          reads += 1;
          throw PlatformException(
            code: 'Exception',
            message: 'javax.crypto.BadPaddingException',
          );
        }
        if (call.method == 'delete' || call.method == 'deleteAll') return null;
        if (call.method == 'write') {
          throw PlatformException(code: 'Exception', message: 'keystore gone');
        }
        return null;
      },
    );
  }

  setUp(() async {
    mockBrokenKeystore();
    SharedPreferences.setMockInitialValues({});
    store = TokenStore(await SharedPreferences.getInstance());
  });

  test('reading a token reports absent rather than throwing', () async {
    expect(await store.accessToken, isNull);
    expect(await store.refreshToken, isNull);
  });

  test('the unreadable entry is dropped, not read forever', () async {
    await store.accessToken;
    await store.accessToken;
    expect(reads, 1, reason: 'a failed read must be remembered, not repeated');
  });

  test('a session still works in memory when the keystore cannot hold it',
      () async {
    // Writing fails too, but the app must not lose the session it just got.
    await store.saveTokens(access: 'fresh-access', refresh: 'fresh-refresh');

    expect(await store.accessToken, 'fresh-access');
    expect(await store.refreshToken, 'fresh-refresh');
  });

  test('signing out does not throw when the keystore is broken', () async {
    await store.saveTokens(access: 'a', refresh: 'r');
    await store.clearTokens();
    expect(await store.accessToken, isNull);
  });

  test('a request still goes out, and is answered', () async {
    // The reported failure, end to end: signing in on a phone whose keystore
    // cannot be read must reach the server.
    var sent = 0;
    final client = ApiClient(store)
      ..adapters = _Adapter((options) async {
        sent += 1;
        expect(options.headers.containsKey('Authorization'), isFalse,
            reason: 'there is no readable token, so none should be attached');
        return ResponseBody.fromString('{"ok":true}', 200, headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        });
      });

    final result = await client.post('/auth/login', body: {'identifier': 'x'});

    expect(sent, 1, reason: 'the request never left the app');
    expect((result as Map)['ok'], isTrue);
    client.dispose();
  });

  test('an unexplained transport failure says more than "something went wrong"',
      () async {
    final client = ApiClient(store)
      ..adapters = _Adapter((options) async {
        throw DioException(
          requestOptions: options,
          type: DioExceptionType.unknown,
          error: 'SocketException: Failed host lookup',
        );
      });

    try {
      await client.get('/items', cache: false);
      fail('expected a failure');
    } catch (error) {
      final message = error.toString();
      expect(message, isNot(equals('Something went wrong.')));
      expect(message, contains('Failed host lookup'),
          reason: 'the only description that exists must reach the user');
    }
    client.dispose();
  });
}

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
