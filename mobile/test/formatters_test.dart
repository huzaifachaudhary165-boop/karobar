import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/formatters.dart';
import 'package:karobar/core/widgets/karobar_logo.dart';

void main() {
  group('money formatting', () {
    test('uses Indian/Pakistani grouping, not Western', () {
      expect(Fmt.money(1234567.89, symbol: 'Rs '), 'Rs 12,34,567.89');
      expect(Fmt.money(100000, symbol: 'Rs ', decimals: false), 'Rs 1,00,000');
      expect(Fmt.money(999, symbol: 'Rs ', decimals: false), 'Rs 999');
      expect(Fmt.money(1000, symbol: 'Rs ', decimals: false), 'Rs 1,000');
    });

    test('keeps the sign outside the currency symbol', () {
      expect(Fmt.money(-4500, symbol: 'Rs ', decimals: false), '-Rs 4,500');
    });

    test('treats null as zero rather than throwing', () {
      expect(Fmt.money(null, symbol: 'Rs '), 'Rs 0.00');
    });

    test('compacts with lakh and crore', () {
      expect(Fmt.compactMoney(150000, symbol: 'Rs '), 'Rs 1.50L');
      expect(Fmt.compactMoney(25000000, symbol: 'Rs '), 'Rs 2.50Cr');
      expect(Fmt.compactMoney(4500, symbol: 'Rs '), 'Rs 4.5K');
      expect(Fmt.compactMoney(750, symbol: 'Rs '), 'Rs 750');
    });
  });

  group('quantity formatting', () {
    test('drops meaningless decimals', () {
      expect(Fmt.qty(5), '5');
      expect(Fmt.qty(5.0), '5');
      expect(Fmt.qty(2.5), '2.5');
      expect(Fmt.qty(null), '0');
    });
  });

  group('dates', () {
    test('describes recent days in words', () {
      final now = DateTime.now();
      expect(Fmt.relative(now), 'Today');
      expect(Fmt.relative(now.subtract(const Duration(days: 1))), 'Yesterday');
      expect(Fmt.relative(now.subtract(const Duration(days: 3))), '3 days ago');
    });

    test('parses ISO dates and rejects junk', () {
      expect(Fmt.parseDate('2026-07-28')?.year, 2026);
      expect(Fmt.parseDate('not a date'), isNull);
      expect(Fmt.parseDate(null), isNull);
    });
  });

  group('text', () {
    test('builds initials from a name', () {
      expect(Fmt.initials('Ahmed Traders'), 'AT');
      expect(Fmt.initials('Bilal'), 'B');
      expect(Fmt.initials('   '), '?');
    });
  });

  testWidgets('logo renders the Urdu wordmark right-to-left', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: Center(child: KarobarLogo())),
      ),
    );

    expect(find.text('کاروبار'), findsOneWidget);
    expect(find.text('KAROBAR'), findsOneWidget);

    final directionality = tester.widget<Directionality>(
      find
          .ancestor(
            of: find.text('کاروبار'),
            matching: find.byType(Directionality),
          )
          .first,
    );
    expect(directionality.textDirection, TextDirection.rtl);
  });
}
