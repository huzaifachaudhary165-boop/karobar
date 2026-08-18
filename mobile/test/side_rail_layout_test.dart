import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The rail has to lay out, not merely compile.
///
/// A calculator was once put into `NavigationRail.trailing` and threw during
/// layout, taking the whole screen with it: the app bar painted and everything
/// below it was black. The analyzer was clean and every other test passed,
/// because a constraint error only happens when the real thing is assembled.
///
/// The calculator is a destination of its own now, but the lesson stands — so
/// this builds the rail the way the shell does and asserts it lays out.
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
                  NavigationRailDestination(
                    icon: Icon(Icons.calculate_outlined),
                    label: Text('Calculator'),
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

  testWidgets('the rail lays out', (tester) async {
    await pumpRail(tester, height: 900);
    expect(tester.takeException(), isNull);
  });

  testWidgets('all five destinations are there', (tester) async {
    await pumpRail(tester, height: 900);

    for (final name in ['Home', 'Parties', 'Invoices', 'Items', 'Calculator']) {
      expect(find.text(name), findsOneWidget, reason: name);
    }
  });

  testWidgets('a short laptop window does not blow up either', (tester) async {
    // 768 high with an app bar above is where the column runs out of room,
    // and where an unbounded-height mistake shows itself.
    await pumpRail(tester, height: 600);
    expect(tester.takeException(), isNull);
  });
}
