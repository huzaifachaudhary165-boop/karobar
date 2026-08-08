import 'package:flutter/material.dart';

import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import 'batches_sheet.dart';
import 'serials_sheet.dart';

/// The part of the item form that asks how closely this item is followed.
///
/// Three shops out of four never touch it. A chemist has to know which batch a
/// strip came from and when it expires; a mobile shop has to know which handset
/// went to which customer and whether it is still in warranty; a kiryana shop
/// selling sugar has neither question. So it is off unless asked for, and the
/// buttons that open the lists only appear once it is on.
class TrackingCard extends StatelessWidget {
  const TrackingCard({
    super.key,
    required this.batches,
    required this.expiry,
    required this.serial,
    required this.onBatches,
    required this.onExpiry,
    required this.onSerial,
    required this.itemId,
    required this.itemName,
  });

  final bool batches;
  final bool expiry;
  final bool serial;
  final ValueChanged<bool> onBatches;
  final ValueChanged<bool> onExpiry;
  final ValueChanged<bool> onSerial;

  /// Null while the item is still being created. Batches and serials belong to
  /// an item that exists — offering to add them first asks what to attach them
  /// to.
  final String? itemId;
  final String itemName;

  bool get _anyOn => batches || expiry || serial;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(context.t('Track this item closely'), style: theme.textTheme.titleSmall),
          const SizedBox(height: 2),
          Text(
            context.t('Most items need none of this. Turn it on for medicines, '
                'cosmetics, phones — anything where which one matters.'),
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.textTheme.bodySmall?.color?.withValues(alpha: 0.75),
            ),
          ),
          const SizedBox(height: 6),

          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: Text(context.t('Batch numbers')),
            subtitle: Text(context.t('Stock arrives in lots you can tell apart')),
            value: batches,
            onChanged: onBatches,
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: Text(context.t('Expiry dates')),
            subtitle: Text(context.t('Oldest stock is sold first, expired stock is not sold')),
            value: expiry,
            onChanged: onExpiry,
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: Text(context.t('Serial numbers')),
            subtitle: Text(context.t('Each piece is its own — IMEI, engine number, warranty')),
            value: serial,
            onChanged: onSerial,
          ),

          if (_anyOn) ...[
            const SizedBox(height: 6),
            if (itemId == null)
              Text(
                context.t('Save the item first, then add its batches and serials here.'),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.primary,
                ),
              )
            else
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (batches || expiry)
                    OutlinedButton.icon(
                      onPressed: () => showBatchesSheet(
                        context,
                        itemId: itemId!,
                        itemName: itemName,
                        withExpiry: expiry,
                      ),
                      icon: const Icon(Icons.inventory_2_outlined, size: 18),
                      label: Text(context.t('Batches')),
                    ),
                  if (serial)
                    OutlinedButton.icon(
                      onPressed: () => showSerialsSheet(
                        context,
                        itemId: itemId!,
                        itemName: itemName,
                      ),
                      icon: const Icon(Icons.pin_outlined, size: 18),
                      label: Text(context.t('Serial numbers')),
                    ),
                ],
              ),
          ],
        ],
      ),
    );
  }
}
