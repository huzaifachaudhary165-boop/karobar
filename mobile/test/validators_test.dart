import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/validators.dart';

/// The password rules here must match `password_strength_issues` in
/// `backend/app/core/security.py` exactly.
///
/// When they drift, the form accepts a password, the request goes out, and the
/// server rejects it with a message that arrives as a snackbar rather than
/// attached to the field — which is how sign-up came to look like it failed for
/// no reason. The sign-up form used to check length and a digit but not a
/// letter, so "12345678" passed here and failed there.
void main() {
  group('password rules mirror the backend', () {
    test('a password meeting every rule has no problems', () {
      expect(Validators.passwordProblems('karobar123'), isEmpty);
    });

    test('too short is reported', () {
      expect(Validators.passwordProblems('ab1'), contains('at least 8 characters'));
    });

    test('all digits is rejected for having no letter', () {
      // The exact case the old sign-up validator let through.
      expect(Validators.passwordProblems('12345678'), contains('a letter'));
    });

    test('all letters is rejected for having no number', () {
      expect(Validators.passwordProblems('abcdefgh'), contains('a number'));
    });

    test('every failing rule is reported at once, not one at a time', () {
      // Three round trips to learn three rules is three chances to give up.
      expect(Validators.passwordProblems('abc'), hasLength(2));
      expect(Validators.passwordProblems(''), hasLength(3));
    });

    test('exactly eight characters is accepted, not rejected off by one', () {
      expect(Validators.passwordProblems('abcdefg1'), isEmpty);
    });

    test('symbols count as neither a letter nor a number', () {
      expect(
        Validators.passwordProblems('!@#\$%^&*'),
        containsAll(<String>['a number', 'a letter']),
      );
    });

    // Verified against the backend directly: `password_strength_issues` uses
    // Python's `isalpha`/`isdigit`, which accept every script. An ASCII-only
    // check here would block a password the server accepts, which is the worse
    // direction to get wrong — the person cannot sign up at all.
    test('a non-Latin letter still counts as a letter', () {
      expect(Validators.passwordProblems('کاروبار12345'), isEmpty);
    });

    test('Arabic-Indic digits still count as numbers', () {
      expect(Validators.passwordProblems('karobar١٢٣٤٥٦٧٨'), isEmpty);
    });
  });
}
