import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/widgets/rail_calculator.dart';

/// Whether the rail calculator actually fits where it is put.
///
/// A keypad that overflows its column paints red-and-yellow stripes across the
/// screen and is the sort of thing that only shows up on somebody else's
/// monitor. The rail is 172 wide; these check the whole keypad lands inside
/// that and inside the height a short window leaves it.
void main() {
  Future<void> at(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: size.width,
            child: const SingleChildScrollView(child: RailCalculator()),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('it fits the rail without overflowing', (tester) async {
    await at(tester, const Size(172, 900));
    expect(tester.takeException(), isNull);
  });

  testWidgets('every key is reachable at that width', (tester) async {
    await at(tester, const Size(172, 900));

    for (final key in ['C', '⌫', '%', '÷', '7', '8', '9', '×', '4', '5', '6',
                       '−', '1', '2', '3', '+', '0', '.', '=']) {
      expect(find.widgetWithText(InkWell, key), findsOneWidget, reason: key);
    }
  });

  testWidgets('a short window scrolls rather than overflowing', (tester) async {
    // A laptop at 768 high, with an app bar and four destinations above this.
    await at(tester, const Size(172, 260));
    expect(tester.takeException(), isNull);
  });

  testWidgets('no key is too small to hit', (tester) async {
    await at(tester, const Size(172, 900));

    for (final key in ['7', '=', 'C']) {
      final size = tester.getSize(find.widgetWithText(InkWell, key));
      expect(size.height, greaterThanOrEqualTo(28), reason: key);
      expect(size.width, greaterThanOrEqualTo(28), reason: key);
    }
  });
}
