import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/screen.dart';

/// How much room a screen has, and what follows from it.
///
/// Karobar was built for a phone and then put in a browser and on a desktop. A
/// phone layout on a wide screen is not merely ugly: a bill row stretched
/// across 1900 pixels puts the customer's name and the amount at opposite ends
/// of the desk, and a bottom bar puts the tabs at the furthest point from where
/// anyone is looking.
void main() {
  /// Builds [child] as if the window were [width] wide.
  Future<void> at(WidgetTester tester, double width, Widget child) {
    tester.view.physicalSize = Size(width, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    return tester.pumpWidget(MaterialApp(home: Scaffold(body: child)));
  }

  ScreenSize? seen;
  Widget probe() => Builder(
        builder: (context) {
          seen = context.screen;
          return const SizedBox.shrink();
        },
      );

  group('which size a window is', () {
    testWidgets('a phone is compact', (tester) async {
      await at(tester, 390, probe());
      expect(seen, ScreenSize.compact);
    });

    testWidgets('a tablet or a split window is medium', (tester) async {
      await at(tester, 800, probe());
      expect(seen, ScreenSize.medium);
    });

    testWidgets('a maximised browser is expanded', (tester) async {
      await at(tester, 1600, probe());
      expect(seen, ScreenSize.expanded);
    });

    testWidgets('the boundaries belong to the larger size', (tester) async {
      await at(tester, 600, probe());
      expect(seen, ScreenSize.medium);
      await at(tester, 1024, probe());
      expect(seen, ScreenSize.expanded);
    });

    testWidgets('one pixel under a boundary is still the smaller size',
        (tester) async {
      await at(tester, 599, probe());
      expect(seen, ScreenSize.compact);
      await at(tester, 1023, probe());
      expect(seen, ScreenSize.medium);
    });
  });

  group('what follows from it', () {
    test('a phone keeps its bottom bar, everything else gets a rail', () {
      expect(ScreenSize.compact.usesSideRail, isFalse);
      expect(ScreenSize.medium.usesSideRail, isTrue);
      expect(ScreenSize.expanded.usesSideRail, isTrue);
    });

    test('only a desktop puts two fields on a row', () {
      // A tablet is wide enough for a rail and not wide enough for two columns
      // of inputs — pairing them there makes both too narrow to read.
      expect(ScreenSize.compact.formColumns, 1);
      expect(ScreenSize.medium.formColumns, 1);
      expect(ScreenSize.expanded.formColumns, 2);
    });

    test('compact and wide are opposites, never both', () {
      for (final size in ScreenSize.values) {
        expect(size.isCompact, isNot(size.isWide), reason: '$size');
      }
    });
  });

  group('content stops growing', () {
    testWidgets('a narrow window keeps every pixel it has', (tester) async {
      // On a phone this widget must take nothing away. Measured rather than
      // asserted against widget types, because what matters is the width the
      // child ends up with, not how it got there.
      await at(
        tester,
        390,
        const ReadableWidth(
          maxWidth: 900,
          child: SizedBox(key: ValueKey('c'), width: double.infinity, height: 10),
        ),
      );

      expect(tester.getSize(find.byKey(const ValueKey('c'))).width, 390);
    });

    testWidgets('a wide window is capped and centred', (tester) async {
      await at(
        tester,
        1600,
        const ReadableWidth(
          maxWidth: 900,
          padHorizontally: false,
          child: SizedBox(key: ValueKey('c'), width: double.infinity, height: 10),
        ),
      );

      // Exactly the cap, not merely under it: a zero-width child would pass a
      // less-than check while showing the shopkeeper nothing at all.
      expect(tester.getSize(find.byKey(const ValueKey('c'))).width, 900);
    });
  });

  group('fields side by side', () {
    const a = SizedBox(key: ValueKey('a'), height: 10);
    const b = SizedBox(key: ValueKey('b'), height: 10);

    testWidgets('stacked on a phone', (tester) async {
      await at(tester, 390, const FormRow(children: [a, b]));

      final first = tester.getTopLeft(find.byKey(const ValueKey('a')));
      final second = tester.getTopLeft(find.byKey(const ValueKey('b')));
      expect(second.dy, greaterThan(first.dy), reason: 'b sits below a');
      expect(second.dx, first.dx, reason: 'and starts at the same edge');
    });

    testWidgets('side by side on a desktop', (tester) async {
      await at(tester, 1600, const FormRow(children: [a, b]));

      final first = tester.getTopLeft(find.byKey(const ValueKey('a')));
      final second = tester.getTopLeft(find.byKey(const ValueKey('b')));
      expect(second.dx, greaterThan(first.dx), reason: 'b sits beside a');
      expect(second.dy, first.dy, reason: 'and on the same line');
    });

    testWidgets('a single field is passed straight through', (tester) async {
      // No Row, no Column, no Expanded — nothing to disturb a field that was
      // laid out correctly already.
      await at(tester, 1600, const FormRow(children: [a]));
      expect(find.byKey(const ValueKey('a')), findsOneWidget);
      expect(find.byType(Row), findsNothing);
    });

    testWidgets('no fields renders nothing rather than throwing',
        (tester) async {
      await at(tester, 1600, const FormRow(children: []));
      expect(find.byType(SizedBox), findsWidgets);
    });
  });
}
