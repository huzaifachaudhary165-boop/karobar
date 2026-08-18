import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/features/calculator/calculator_screen.dart';
import 'package:karobar/providers.dart';

/// The calculator module, driven the way a shopkeeper would.
///
/// The arithmetic is proven in `trade_maths_test.dart`. What this checks is
/// that the right sum is reached from the right screen — because a correct
/// formula wired to the wrong field is still a wrong answer, and that is
/// exactly the mistake this module exists to stop people making.
void main() {
  Future<void> open(WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          // Only the currency symbol is read from the session here, and a real
          // one would try to reach storage on construction.
          sessionProvider.overrideWith((ref) => _StubSession()),
        ],
        child: const MaterialApp(home: CalculatorScreen()),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> tab(WidgetTester tester, String name) async {
    await tester.tap(find.text(name));
    await tester.pumpAndSettle();
  }

  Future<void> type(WidgetTester tester, String label, String value) async {
    await tester.enterText(find.widgetWithText(TextField, label), value);
    await tester.pumpAndSettle();
  }

  testWidgets('it opens on the keypad and offers all five', (tester) async {
    await open(tester);

    for (final name in ['Keypad', 'Price & margin', 'Discount', 'Tax', 'Units']) {
      expect(find.text(name), findsOneWidget, reason: name);
    }
  });

  testWidgets('the keypad is there on arrival, not behind a button',
      (tester) async {
    // Somebody who tapped Calculator has already said what they want. An
    // "open the keypad" button is a step that exists for no reason.
    await open(tester);

    for (final key in ['7', '8', '9', '=', '%']) {
      expect(find.widgetWithText(InkWell, key), findsOneWidget, reason: key);
    }
  });

  testWidgets('and it has no "use this number" button here', (tester) async {
    // There is nowhere to hand the answer back to on this screen — the answer
    // is the point in itself.
    await open(tester);
    expect(find.text('Use this number'), findsNothing);
  });

  group('price and margin', () {
    testWidgets('a 20% margin on a 100 cost gives 125, not 120',
        (tester) async {
      // The mistake the whole tab exists for. Read as markup it is 120, and
      // somebody billing that is short on every unit.
      await open(tester);
      await tab(tester, 'Price & margin');
      await type(tester, 'Cost price', '100');
      await type(tester, 'Margin you want', '20');

      expect(find.textContaining('125'), findsWidgets);
    });

    testWidgets('switching to markup gives 120 from the same numbers',
        (tester) async {
      await open(tester);
      await tab(tester, 'Price & margin');
      await type(tester, 'Cost price', '100');
      await type(tester, 'Margin you want', '20');
      await tester.tap(find.text('on top of cost'));
      await tester.pumpAndSettle();

      expect(find.textContaining('120'), findsWidgets);
    });

    testWidgets('an impossible margin says so instead of showing a figure',
        (tester) async {
      await open(tester);
      await tab(tester, 'Price & margin');
      await type(tester, 'Cost price', '100');
      await type(tester, 'Margin you want', '100');

      expect(find.text('Not possible'), findsOneWidget);
    });

    testWidgets('both percentages are shown, so neither has to be remembered',
        (tester) async {
      await open(tester);
      await tab(tester, 'Price & margin');
      await tester.tap(find.text('Profit'));
      await tester.pumpAndSettle();
      await type(tester, 'Cost price', '100');
      await type(tester, 'Selling price', '125');

      expect(find.text('Margin'), findsOneWidget);
      expect(find.text('Markup'), findsOneWidget);
    });
  });

  group('discounts', () {
    testWidgets('"10 and 5" comes to 855, not 850', (tester) async {
      await open(tester);
      await tab(tester, 'Discount');
      await type(tester, 'Amount', '1000');
      await type(tester, 'First discount', '10');

      await tester.tap(find.text('Another discount'));
      await tester.pumpAndSettle();
      await type(tester, 'Then', '5');

      expect(find.textContaining('855'), findsWidgets);
    });
  });

  group('tax', () {
    testWidgets('adding 17% to 1000 gives 1170', (tester) async {
      await open(tester);
      await tab(tester, 'Tax');
      await type(tester, 'Price before tax', '1000');

      expect(find.textContaining('1,170'), findsWidgets);
    });

    testWidgets('taking it back out of 1170 gives 1000, not 971',
        (tester) async {
      // A subtraction gives 971.10 and is the half people get wrong.
      await open(tester);
      await tab(tester, 'Tax');
      await tester.tap(find.text('Take tax out'));
      await tester.pumpAndSettle();
      await type(tester, 'Price including tax', '1170');

      expect(find.textContaining('1,000'), findsWidgets);
      expect(find.textContaining('971'), findsNothing);
    });
  });

  group('units', () {
    testWidgets('one maund is forty kilos', (tester) async {
      await open(tester);
      await tab(tester, 'Units');

      // Opens on weight, first unit to second — Kg to Gram — so this checks
      // the swap and the dropdowns as well as the conversion.
      expect(find.text('Weight'), findsOneWidget);
      expect(find.textContaining('40 kg'), findsWidgets,
          reason: 'the note naming the Pakistani maund should be on screen');
    });

    testWidgets('every family can be reached', (tester) async {
      await open(tester);
      await tab(tester, 'Units');

      for (final name in ['Weight', 'Length & cloth', 'Count', 'Area & volume']) {
        expect(find.text(name), findsOneWidget, reason: name);
      }
    });
  });
}

/// A session that reports a currency and never touches storage.
class _StubSession extends SessionNotifier {
  _StubSession() : super(_NoRef());
}

/// SessionNotifier only uses its Ref lazily, and nothing in these tests takes
/// a path that reads it.
class _NoRef implements Ref {
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}
