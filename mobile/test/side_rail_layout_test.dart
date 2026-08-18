import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/widgets/rail_calculator.dart';

/// The rail has to lay out, not merely compile.
///
/// Putting the calculator into `NavigationRail.trailing` inside an `Expanded`
/// threw during layout and took the whole screen with it — the app bar painted
/// and everything below it was black. Nothing in the analyzer or the other
/// tests could see that, because it is a constraint error at run time on a
/// widget none of them built.
///
/// So this builds the real thing, the way the shell does.
void main() {
  Future<void> pumpRail(WidgetTester tester, {required double height}) async {
    tester.view.physicalSize = Size(1400, height);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Row(
            children: [
              NavigationRail(
                selectedIndex: 0,
                labelType: NavigationRailLabelType.all,
                minWidth: 172,
                groupAlignment: -1,
                leading: const Padding(
                  padding: EdgeInsets.only(top: 12, bottom: 6),
                  child: CircleAvatar(radius: 18),
                ),
                trailing: const RailCalculator(),
                destinations: const [
                  NavigationRailDestination(
                    icon: Icon(Icons.dashboard_outlined),
                    label: Text('Home'),
                  ),
                  NavigationRailDestination(
                    icon: Icon(Icons.people_outline),
                    label: Text('Parties'),
                  ),
                  NavigationRailDestination(
                    icon: Icon(Icons.receipt_long_outlined),
                    label: Text('Invoices'),
                  ),
                  NavigationRailDestination(
                    icon: Icon(Icons.inventory_2_outlined),
                    label: Text('Items'),
                  ),
                ],
              ),
              const Expanded(child: SizedBox.expand()),
            ],
          ),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('the rail lays out with the calculator in it', (tester) async {
    await pumpRail(tester, height: 900);
    expect(tester.takeException(), isNull);
  });

  testWidgets('and the destinations are still there', (tester) async {
    await pumpRail(tester, height: 900);

    for (final name in ['Home', 'Parties', 'Invoices', 'Items']) {
      expect(find.text(name), findsOneWidget, reason: name);
    }
  });

  testWidgets('the calculator is reachable below them', (tester) async {
    await pumpRail(tester, height: 900);
    expect(find.widgetWithText(InkWell, '7'), findsOneWidget);
  });

  testWidgets('a short laptop window does not blow up either', (tester) async {
    // 768 high with an app bar above is where the column runs out of room,
    // and where an unbounded-height mistake shows itself.
    await pumpRail(tester, height: 600);
    expect(tester.takeException(), isNull);
  });
}
