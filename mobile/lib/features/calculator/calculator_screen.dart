import 'package:flutter/material.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/screen.dart';
import '../../core/widgets/shop_calculator.dart';

/// The calculator, and nothing else.
///
/// It had tabs once — margin, discounts, tax, unit conversion — and they were
/// four screens pretending to be one. Somebody who taps Calculator wants a
/// calculator, the same one that sits on their counter, and a row of tabs
/// between them and the keys is a row of tabs too many.
///
/// What it does keep is everything a phone's calculator lacks and the machine
/// on the counter has: memory, a running grand total, percent that behaves the
/// way that machine does, square root, and 00 and 000 for the thousands a
/// wholesaler types all day.
class CalculatorScreen extends StatelessWidget {
  const CalculatorScreen({super.key, this.onScreen = true});

  /// Whether this is the tab being looked at.
  ///
  /// The shell builds every tab at once and keeps them alive, so a calculator
  /// that took the keyboard the moment it was built would swallow typing meant
  /// for the dashboard.
  final bool onScreen;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.t('Calculator'))),
      // Held to the width of a real calculator. Keys stretched across a desk
      // are further apart than a hand, and slower than the machine it replaces.
      // Centred rather than pinned to the top, so on a laptop it sits on the
      // page instead of hanging from it with half a screen of white below.
      body: ReadableWidth(
        maxWidth: 440,
        padHorizontally: false,
        // Center outside the scroll view, not in: the scroll view then takes
        // the height of the keypad when it fits and scrolls only when it does
        // not — centred on a laptop, reachable on a small phone.
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
            child: ShopCalculator(listenToKeyboard: onScreen),
          ),
        ),
      ),
    );
  }
}
