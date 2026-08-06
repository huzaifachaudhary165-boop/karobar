import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/loan_preview.dart';

/// The on-screen instalment must equal the one the server stores.
///
/// The same formula exists in two places — Dart for the live preview while a
/// loan is being typed, Python for the figure that is actually saved. Two
/// implementations of one calculation is a real risk, and the failure is
/// quiet: a shopkeeper shown 23,536.74 who then saves a loan of 23,540 has no
/// reason to trust either number again.
///
/// Every expected value here is copied from `backend/tests/test_loan_maths.py`.
/// If one side changes and the other does not, this file fails.
void main() {
  group('the preview agrees with the server', () {
    test('reducing balance matches the standard annuity figure', () {
      // 500,000 over 24 months at 12% — a widely published number.
      expect(
        previewInstalment(principal: 500000, months: 24, rate: 12),
        23536.74,
      );
    });

    test('flat rate spreads the whole interest evenly', () {
      // 12% flat on 100,000 for 2 years = 24,000 interest, so 124,000 over 24.
      expect(
        previewInstalment(
          principal: 100000,
          months: 24,
          rate: 12,
          interestType: 'flat',
        ),
        5166.67,
      );
    });

    test('an interest-free loan just divides the principal', () {
      expect(
        previewInstalment(
          principal: 60000,
          months: 12,
          rate: 0,
          interestType: 'none',
        ),
        5000.00,
      );
    });

    test('a zero rate is interest-free whatever the type says', () {
      expect(previewInstalment(principal: 60000, months: 12), 5000.00);
      expect(
        previewInstalment(
          principal: 60000,
          months: 12,
          rate: 0,
          interestType: 'flat',
        ),
        5000.00,
      );
    });
  });

  group('flat is not the same offer as reducing', () {
    test('flat costs more at the same headline rate', () {
      final flat = previewInstalment(
        principal: 100000,
        months: 24,
        rate: 12,
        interestType: 'flat',
      )!;
      final reducing =
          previewInstalment(principal: 100000, months: 24, rate: 12)!;

      expect(flat, greaterThan(reducing));
    });

    test('the difference is shown, not hidden', () {
      // The whole reason the total is on screen: a borrower comparing "12%"
      // against "12% flat" should see what the second one really costs.
      final flat = previewTotalInterest(
        principal: 100000,
        months: 24,
        rate: 12,
        interestType: 'flat',
      )!;
      final reducing =
          previewTotalInterest(principal: 100000, months: 24, rate: 12)!;

      expect(flat, 24000);
      expect(reducing, lessThan(flat * 0.6),
          reason: 'flat is close to double the real cost over two years');
    });
  });

  group('an incomplete form shows nothing rather than a wrong number', () {
    test('no principal yet', () {
      expect(previewInstalment(principal: null, months: 12, rate: 10), isNull);
      expect(previewInstalment(principal: 0, months: 12, rate: 10), isNull);
    });

    test('no term yet', () {
      expect(previewInstalment(principal: 50000, months: null), isNull);
      expect(previewInstalment(principal: 50000, months: 0), isNull);
    });

    test('a negative amount is not a loan', () {
      expect(previewInstalment(principal: -5000, months: 12), isNull);
    });

    test('the total is absent whenever the instalment is', () {
      expect(previewTotalInterest(principal: null, months: 12), isNull);
    });
  });

  group('rounding', () {
    test('the figure is always to the paisa, never a long decimal', () {
      for (final months in [7, 11, 13, 17, 23, 37]) {
        final value = previewInstalment(
          principal: 83333,
          months: months,
          rate: 17.5,
        )!;
        expect(
          (value * 100) % 1,
          0,
          reason: '$months months produced $value, which is not a clean paisa',
        );
      }
    });

    test('a half rounds up, matching the server rather than Dart defaults', () {
      // 100.005 a month is exactly the case where round-half-even would give
      // 100.00 and the server gives 100.01.
      expect(previewInstalment(principal: 1000.05, months: 10), 100.01);
    });
  });

  group('interest-free borrowing, which is the common case here', () {
    test('a family loan repays only the principal', () {
      expect(
        previewTotalInterest(
          principal: 120000,
          months: 12,
          rate: 0,
          interestType: 'none',
        ),
        0,
      );
    });

    test('twelve equal instalments add back up to what was borrowed', () {
      final each = previewInstalment(
        principal: 120000,
        months: 12,
        rate: 0,
        interestType: 'none',
      )!;
      expect(each * 12, 120000);
    });
  });
}
