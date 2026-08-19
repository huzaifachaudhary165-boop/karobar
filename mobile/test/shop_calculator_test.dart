import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/widgets/calculator_sheet.dart';
import 'package:karobar/core/widgets/shop_calculator.dart';

/// The calculator as a shopkeeper meets it.
///
/// The arithmetic is proven in `calculator_engine_test.dart`. What this checks
/// is that every key on the counter machine is on this one and wired to the
/// right thing — a correct engine behind a keypad missing M+ is still a
/// calculator somebody goes back to their own machine for.
void main() {
  Future<void> open(WidgetTester tester) async {
    tester.view.physicalSize = const Size(500, 1100);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: ShopCalculator()),
        ),
      ),
    );
    await tester.pump();
  }

  Future<void> press(WidgetTester tester, List<String> keys) async {
    for (final key in keys) {
      await tester.tap(find.widgetWithText(InkWell, key));
      await tester.pump();
    }
  }

  void shows(String value) => expect(find.text(value), findsWidgets);

  group('every key the counter machine has', () {
    testWidgets('all of them are on it', (tester) async {
      await open(tester);

      for (final key in [
        'MC', 'MR', 'M−', 'M+', 'GT',
        'AC', 'C', '⌫', '√', '÷',
        '7', '8', '9', '%', '×',
        '4', '5', '6', '±', '−',
        '1', '2', '3', '00', '+',
        '0', '.', '000', '=',
      ]) {
        expect(find.widgetWithText(InkWell, key), findsOneWidget, reason: key);
      }
    });

    testWidgets('and nothing invented that is not', (tester) async {
      // The three fixed percentages were made up — no machine has −10%, −5%
      // and +17% keys, and a shop's discounts are not those three numbers.
      await open(tester);
      expect(find.text('−10%'), findsNothing);
      expect(find.text('+17%'), findsNothing);
    });
  });

  group('the sums', () {
    testWidgets('multiplies', (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '×', '8', '=']);
      shows('96');
    });

    testWidgets('percent takes a share of the left-hand side', (tester) async {
      await open(tester);
      await press(tester, ['1', '0', '0', '0', '−', '1', '0', '%', '=']);
      shows('900');
    });

    testWidgets('square root', (tester) async {
      await open(tester);
      await press(tester, ['1', '4', '4', '√']);
      shows('12');
    });

    testWidgets('000 is one key for a thousand', (tester) async {
      await open(tester);
      await press(tester, ['5', '000']);
      shows('5000');
    });
  });

  group('memory and the running total', () {
    testWidgets('what is in memory is shown, not hidden', (tester) async {
      // A figure in memory that nobody can see is one that gets used by
      // accident on the next sum.
      await open(tester);
      await press(tester, ['5', '0', '0', 'M+']);

      expect(find.textContaining('M 500'), findsOneWidget);
    });

    testWidgets('recalling brings it back', (tester) async {
      await open(tester);
      await press(tester, ['5', '0', '0', 'M+', 'C', 'MR']);
      shows('500');
    });

    testWidgets('clearing memory takes the marker away', (tester) async {
      await open(tester);
      await press(tester, ['5', '0', '0', 'M+', 'MC']);
      expect(find.textContaining('M 500'), findsNothing);
    });

    testWidgets('the grand total adds up every answer', (tester) async {
      await open(tester);
      await press(tester, ['1', '0', '×', '5', '=']);
      await press(tester, ['2', '0', '×', '3', '=']);
      await press(tester, ['GT']);
      shows('110');
    });

    testWidgets('a stray tap on GT cannot lose a long column', (tester) async {
      // Shown on a tap, cleared only on a hold.
      await open(tester);
      await press(tester, ['1', '0', '+', '1', '0', '=', 'GT']);
      shows('20');

      await tester.longPress(find.widgetWithText(InkWell, 'GT'));
      await tester.pump();
      await press(tester, ['GT']);
      shows('0');
    });
  });

  group('handing the answer back', () {
    testWidgets('the screen has no use button — the answer is the point',
        (tester) async {
      await open(tester);
      expect(find.text('Use this number'), findsNothing);
    });

    testWidgets('a field that asked for a number gets one', (tester) async {
      double? handedBack;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () async {
                  handedBack = await showCalculator(context);
                },
                child: const Text('open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      // Half-finished on purpose: Use must settle it and hand back 96, not the
      // 8 still on the display.
      await press(tester, ['1', '2', '×', '8']);
      await tester.tap(find.text('Use this number'));
      await tester.pumpAndSettle();

      expect(handedBack, 96);
    });
  });
}
