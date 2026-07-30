import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/router/app_router.dart';
import 'package:karobar/providers.dart';

/// Routing rules, tested as plain data.
///
/// A wrong rule here does not misroute one screen. Two rules that disagree send
/// the user back and forth until go_router gives up and shows "No screen at
/// /home" — and the only button on that page walked straight back into the same
/// loop, so the app could not be recovered without force-closing it.
///
/// That is exactly what happened: a signed-in user whose shop had not loaded
/// was sent /home -> /register by one rule and /register -> /home by the next.
void main() {
  String? go(
    String path, {
    AuthStatus status = AuthStatus.signedIn,
    bool onboarded = true,
    bool needsBusiness = false,
  }) =>
      resolveRedirect(
        path: path,
        status: status,
        onboarded: onboarded,
        needsBusiness: needsBusiness,
      );

  /// Follows the redirects the way go_router does, and fails on a cycle.
  ///
  /// go_router's own limit is 5 hops; anything that has not settled by 10 is a
  /// loop whatever the exact number.
  String settle(
    String from, {
    AuthStatus status = AuthStatus.signedIn,
    bool onboarded = true,
    bool needsBusiness = false,
  }) {
    final seen = <String>[from];
    var current = from;

    for (var hop = 0; hop < 10; hop++) {
      final next = go(current,
          status: status, onboarded: onboarded, needsBusiness: needsBusiness);
      if (next == null) return current;
      if (seen.contains(next)) {
        fail('redirect loop: ${[...seen, next].join(" -> ")}');
      }
      seen.add(next);
      current = next;
    }
    fail('redirects never settled: ${seen.join(" -> ")}');
  }

  group('a signed-in user whose shop has not loaded', () {
    // The reported bug, in one test.
    test('lands on register and stays there', () {
      expect(settle('/home', needsBusiness: true), '/register');
    });

    test('register does not bounce back to home', () {
      expect(go('/register', needsBusiness: true), isNull);
    });

    test('no starting screen loops', () {
      for (final path in [
        '/', '/home', '/register', '/login', '/onboarding',
        '/forgot-password', '/home/settings', '/home/invoices/new',
      ]) {
        settle(path, needsBusiness: true);
      }
    });
  });

  group('signed out', () {
    test('can reach forgot password without being bounced to login', () {
      expect(go('/forgot-password', status: AuthStatus.signedOut), isNull);
    });

    test('login and register are reachable', () {
      expect(go('/login', status: AuthStatus.signedOut), isNull);
      expect(go('/register', status: AuthStatus.signedOut), isNull);
    });

    test('anything else goes to login', () {
      expect(go('/home', status: AuthStatus.signedOut), '/login');
      expect(go('/home/settings', status: AuthStatus.signedOut), '/login');
    });
  });

  group('first launch', () {
    test('the tour comes before the sign-in form', () {
      expect(
        settle('/', status: AuthStatus.signedOut, onboarded: false),
        '/onboarding',
      );
    });

    test('finishing the tour leads to login and does not return', () {
      // The Skip / Get started bug: with `onboarded` still false the redirect
      // sent the user straight back, so the button looked dead.
      expect(
        settle('/login', status: AuthStatus.signedOut, onboarded: true),
        '/login',
      );
    });

    test('the tour is not shown again once it is done', () {
      expect(go('/onboarding', status: AuthStatus.signedOut), '/login');
    });
  });

  group('normal signed-in use', () {
    test('home stays home', () => expect(go('/home'), isNull));

    test('inner screens are left alone', () {
      expect(go('/home/settings'), isNull);
      expect(go('/home/invoices/new'), isNull);
      expect(go('/home/parties/abc'), isNull);
    });

    test('the auth screens send a signed-in user home', () {
      expect(go('/login'), '/home');
      expect(go('/register'), '/home');
      expect(go('/'), '/home');
    });
  });

  group('while the session is still being restored', () {
    test('everything waits on the splash', () {
      expect(go('/home', status: AuthStatus.unknown), '/');
      expect(go('/login', status: AuthStatus.unknown), '/');
      expect(go('/', status: AuthStatus.unknown), isNull);
    });
  });

  test('no combination of states produces a loop from any screen', () {
    const paths = [
      '/', '/home', '/login', '/register', '/onboarding', '/forgot-password',
      '/home/settings', '/home/items/new',
    ];

    for (final status in AuthStatus.values) {
      for (final onboarded in [true, false]) {
        for (final needsBusiness in [true, false]) {
          for (final path in paths) {
            settle(path,
                status: status,
                onboarded: onboarded,
                needsBusiness: needsBusiness);
          }
        }
      }
    }
  });
}
