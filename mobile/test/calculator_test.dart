import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/widgets/calculator_sheet.dart';

/// The calculator a shopkeeper would otherwise leave the app to find.
///
/// The answer has to be right and it has to come back — a calculator that
/// gives a number you then retype is the phone's calculator with extra steps,
/// and leaving Karobar mid-bill is how a half-made bill gets lost.
void main() {
  double? handedBack;

  Future<void> open(WidgetTester tester, {double? start}) async {
    handedBack = null;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () async {
                handedBack = await showCalculator(context, start: start);
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
  }

  Future<void> press(WidgetTester tester, List<String> keys) async {
    for (final key in keys) {
      await tester.tap(find.widgetWithText(InkWell, key).last);
      await tester.pump();
    }
  }

  Future<void> use(WidgetTester tester) async {
    await tester.tap(find.text('Use this number'));
    await tester.pumpAndSettle();
  }

  group('the arithmetic', () {
    testWidgets('multiplies, which is most of a wholesaler\'s day',
        (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '×', '8', '=']);
      await use(tester);

      expect(handedBack, 96);
    });

    testWidgets('divides a sack into what it holds', (tester) async {
      await open(tester);
      await press(tester, ['5', '0', '÷', '4', '=']);
      await use(tester);

      expect(handedBack, 12.5);
    });

    testWidgets('dividing by nothing leaves the number alone', (tester) async {
      // A slip, not an answer. Infinity in a rate field is worse than the
      // number they started with.
      await open(tester);
      await press(tester, ['8', '0', '÷', '0', '=']);
      await use(tester);

      expect(handedBack, 80);
    });

    testWidgets('chains without needing equals between steps', (tester) async {
      // Adding a column is one operator after another, which is how anybody
      // totals a delivery note.
      await open(tester);
      await press(tester, ['1', '0', '+', '2', '0', '+', '5', '=']);
      await use(tester);

      expect(handedBack, 35);
    });
  });

  group('the two percentages a shop actually uses', () {
    testWidgets('taking a discount off', (tester) async {
      await open(tester);
      await press(tester, ['1', '0', '0', '0']);
      await tester.tap(find.text('−10%'));
      await tester.pump();
      await use(tester);

      expect(handedBack, 900);
    });

    testWidgets('putting tax on top', (tester) async {
      await open(tester);
      await press(tester, ['1', '0', '0', '0']);
      await tester.tap(find.text('+17%'));
      await tester.pump();
      await use(tester);

      expect(handedBack, 1170);
    });
  });

  group('handing the answer back', () {
    testWidgets('a half-finished sum is settled first', (tester) async {
      // "12 × 8" then Use must hand back 96, not the 8 still on the display.
      // Getting this wrong puts a quantity into a rate field.
      await open(tester);
      await press(tester, ['1', '2', '×', '8']);
      await use(tester);

      expect(handedBack, 96);
    });

    testWidgets('it opens on the number the field already had', (tester) async {
      await open(tester, start: 250);
      await press(tester, ['+', '5', '0', '=']);
      await use(tester);

      expect(handedBack, 300);
    });

    testWidgets('closing without using it hands back nothing', (tester) async {
      await open(tester);
      await press(tester, ['9', '9']);
      // Dragged away rather than confirmed.
      await tester.tapAt(const Offset(200, 20));
      await tester.pumpAndSettle();

      expect(handedBack, isNull);
    });
  });

  group('keys that catch a slip', () {
    testWidgets('a thousand is one key, not three zeros', (tester) async {
      await open(tester);
      await press(tester, ['5', '000']);
      await use(tester);

      expect(handedBack, 5000);
    });

    testWidgets('backspace takes off the last digit only', (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '3', '⌫']);
      await use(tester);

      expect(handedBack, 12);
    });

    testWidgets('clear puts it back to zero', (tester) async {
      await open(tester);
      await press(tester, ['9', '9', '9', 'C']);
      await use(tester);

      expect(handedBack, 0);
    });

    testWidgets('a second decimal point is ignored', (tester) async {
      await open(tester);
      await press(tester, ['1', '.', '5', '.', '5']);
      await use(tester);

      expect(handedBack, 1.55);
    });
  });
}
