import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/widgets/rail_calculator.dart';

/// The calculator pinned in the side rail.
///
/// A shopkeeper on a laptop keeps one open beside their work anyway, so it
/// lives in the space under the navigation that was running empty to the
/// bottom of the window. Plain on purpose — digits, four operations, percent —
/// with the whole module a screen away for margin, discounts, tax and units.
void main() {
  Future<void> open(WidgetTester tester) async {
    // Tall and narrow, the way the rail actually is.
    tester.view.physicalSize = const Size(200, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SizedBox(width: 180, child: RailCalculator()),
        ),
      ),
    );
  }

  Future<void> press(WidgetTester tester, List<String> keys) async {
    for (final key in keys) {
      await tester.tap(find.widgetWithText(InkWell, key));
      await tester.pump();
    }
  }

  void expectShows(String value) =>
      expect(find.textContaining(value), findsWidgets);

  group('the four operations', () {
    testWidgets('adds', (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '+', '8', '=']);
      expectShows('20');
    });

    testWidgets('subtracts', (tester) async {
      await open(tester);
      await press(tester, ['5', '0', '−', '8', '=']);
      expectShows('42');
    });

    testWidgets('multiplies', (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '×', '8', '=']);
      expectShows('96');
    });

    testWidgets('divides', (tester) async {
      await open(tester);
      await press(tester, ['9', '6', '÷', '8', '=']);
      expectShows('12');
    });

    testWidgets('dividing by nothing leaves the number alone', (tester) async {
      // A slip, not an answer. Infinity is worse than what they started with.
      await open(tester);
      await press(tester, ['8', '0', '÷', '0', '=']);
      expectShows('80');
    });
  });

  group('percent, meaning what a shop means by it', () {
    testWidgets('taking 10% off a thousand takes off a hundred',
        (tester) async {
      // With a sum waiting, % is a share of the left-hand side. A scientific
      // calculator gives 0.1 here, which is not what anybody at a counter
      // wants.
      await open(tester);
      await press(tester, ['1', '0', '0', '0', '−', '1', '0', '%', '=']);
      expectShows('900');
    });

    testWidgets('adding 17% on top', (tester) async {
      await open(tester);
      await press(tester, ['1', '0', '0', '0', '+', '1', '7', '%', '=']);
      expectShows('1170');
    });

    testWidgets('on its own it is just a division by a hundred',
        (tester) async {
      await open(tester);
      await press(tester, ['5', '0', '%']);
      expectShows('0.5');
    });
  });

  group('fixing a slip', () {
    testWidgets('backspace removes the last digit only', (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '3', '⌫']);
      expectShows('12');
    });

    testWidgets('clear puts everything back to zero', (tester) async {
      await open(tester);
      await press(tester, ['9', '9', '+', '1', 'C']);
      expectShows('0');
    });

    testWidgets('a second decimal point is ignored', (tester) async {
      await open(tester);
      await press(tester, ['1', '.', '5', '.', '5']);
      expectShows('1.55');
    });
  });

  group('what it keeps on screen', () {
    testWidgets('the finished sum stays above the answer', (tester) async {
      // One line rather than a tape: there is no room for a tape in a rail,
      // and the thing people look back at is the sum they just did.
      await open(tester);
      await press(tester, ['1', '2', '×', '8', '=']);

      expect(find.textContaining('12 × 8'), findsOneWidget);
      expectShows('96');
    });

    testWidgets('a pending operation is visible before the second number',
        (tester) async {
      await open(tester);
      await press(tester, ['1', '2', '+']);
      expect(find.textContaining('12 +'), findsOneWidget);
    });

    testWidgets('chaining works without pressing equals between steps',
        (tester) async {
      await open(tester);
      await press(tester, ['1', '0', '+', '2', '0', '+', '5', '=']);
      expectShows('35');
    });
  });
}
