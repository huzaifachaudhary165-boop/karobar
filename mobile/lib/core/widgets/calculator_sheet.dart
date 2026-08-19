import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import 'shop_calculator.dart';

/// The calculator, opened over a field that wants a number.
///
/// The same one as the Calculator screen — one keypad, not two that drift
/// apart. The difference is only that this one has somewhere to hand the
/// answer back to, so it offers to.
Future<double?> showCalculator(
  BuildContext context, {
  double? start,
  String? title,
}) {
  return showModalBottomSheet<double>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (sheetContext) => Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null) ...[
              Text(
                context.t(title),
                style: Theme.of(context).textTheme.titleSmall,
              ),
              const SizedBox(height: 8),
            ],
            ShopCalculator(
              start: start,
              // The sheet is already the panel; a second box around the keys
              // is what pushes Use below the fold on a small phone.
              framed: false,
              onUse: (value) => Navigator.pop(sheetContext, value),
            ),
          ],
        ),
      ),
    ),
  );
}
