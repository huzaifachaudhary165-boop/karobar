import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/barcode_sheet.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// What the shopkeeper chose on the batch picker.
///
/// A wrapper rather than a bare `ItemBatch?`, because backing out of the sheet
/// and choosing "sell from the oldest" are different answers and both would
/// arrive as null.
class BatchChoice {
  const BatchChoice(this.batch);

  final ItemBatch? batch;
}

/// Which batch a line comes out of.
///
/// Left alone the server sells from whichever expires first, which is what a
/// shop wants nine times out of ten — this is for the tenth, when the box in
/// the shopkeeper's hand is not that one.
Future<BatchChoice?> showBatchPicker(
  BuildContext context, {
  required String itemId,
  String? selectedId,
}) {
  return showModalBottomSheet<BatchChoice>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _BatchPicker(itemId: itemId, selectedId: selectedId),
  );
}

class _BatchPicker extends ConsumerStatefulWidget {
  const _BatchPicker({required this.itemId, this.selectedId});

  final String itemId;
  final String? selectedId;

  @override
  ConsumerState<_BatchPicker> createState() => _BatchPickerState();
}

class _BatchPickerState extends ConsumerState<_BatchPicker> {
  late final Future<List<ItemBatch>> _future =
      ref.read(stockRepositoryProvider).batches(widget.itemId, inStockOnly: true);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.t('Sell from which batch?'), style: theme.textTheme.titleMedium),
            const SizedBox(height: 10),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.auto_awesome_outlined),
              title: Text(context.t('Oldest first')),
              subtitle: Text(
                context.t('Whatever expires soonest, so nothing is thrown away'),
              ),
              selected: widget.selectedId == null,
              onTap: () => Navigator.pop(context, const BatchChoice(null)),
            ),
            const Divider(height: 20),
            ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(context).height * 0.42,
              ),
              child: FutureBuilder<List<ItemBatch>>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const ListSkeleton(rows: 3, height: 52);
                  }
                  if (snapshot.hasError) {
                    return EmptyState(
                      title: context.t('Could not load batches'),
                      message: snapshot.error.toString(),
                      isError: true,
                    );
                  }

                  // Expired stock is never offered. A shop that sells it is
                  // taking a risk the app should not have helped them take.
                  final rows = (snapshot.data ?? const <ItemBatch>[])
                      .where((batch) => !batch.isExpired)
                      .toList();

                  if (rows.isEmpty) {
                    return EmptyState(
                      title: context.t('Nothing to choose from'),
                      message: context.t('This item has no batch with stock in it '
                          'that is still in date.'),
                      icon: Icons.inventory_2_outlined,
                    );
                  }

                  return ListView.separated(
                    shrinkWrap: true,
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final batch = rows[index];
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        title: Text(batch.batchNumber),
                        subtitle: Text(
                          [
                            '${Fmt.qty(batch.qty)} left',
                            if (batch.expiryDate != null)
                              'expires ${Fmt.date(batch.expiryDate!)}',
                          ].join(' · '),
                        ),
                        trailing: batch.isExpiringSoon
                            ? StatusChip(
                                'partial',
                                label: context.t('${batch.daysToExpiry}d'),
                                dense: true,
                              )
                            : null,
                        selected: batch.id == widget.selectedId,
                        onTap: () => Navigator.pop(context, BatchChoice(batch)),
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Which exact pieces are going out on this line.
///
/// Returns null if the shopkeeper backs out, leaving whatever was already on
/// the line alone.
Future<List<String>?> showSerialPicker(
  BuildContext context, {
  required String itemId,
  required String itemName,
  required int wanted,
  required List<String> already,
}) {
  return showModalBottomSheet<List<String>>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _SerialPicker(
      itemId: itemId,
      itemName: itemName,
      wanted: wanted,
      already: already,
    ),
  );
}

class _SerialPicker extends ConsumerStatefulWidget {
  const _SerialPicker({
    required this.itemId,
    required this.itemName,
    required this.wanted,
    required this.already,
  });

  final String itemId;
  final String itemName;
  final int wanted;
  final List<String> already;

  @override
  ConsumerState<_SerialPicker> createState() => _SerialPickerState();
}

class _SerialPickerState extends ConsumerState<_SerialPicker> {
  late final Future<List<ItemSerial>> _future =
      ref.read(stockRepositoryProvider).serials(widget.itemId, status: 'in_stock');

  late final _chosen = <String>{...widget.already};

  void _toggle(String serial) => setState(() {
        if (!_chosen.remove(serial)) _chosen.add(serial);
      });

  /// Scanning is how a shop with fifty handsets on the shelf finds the one in
  /// their hand — a list of fifty IMEIs is not something anybody reads.
  Future<void> _scan(List<ItemSerial> available) async {
    final code = await scanBarcode(context);
    if (code == null || !mounted) return;

    final match = available
        .where((row) => row.serialNumber.toLowerCase() == code.trim().toLowerCase())
        .firstOrNull;

    if (match == null) {
      showError(context, 'No unsold ${widget.itemName} has the number $code.');
      return;
    }
    if (!_chosen.contains(match.serialNumber)) _toggle(match.serialNumber);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
        child: FutureBuilder<List<ItemSerial>>(
          future: _future,
          builder: (context, snapshot) {
            final available = snapshot.data ?? const <ItemSerial>[];

            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            context.t('Which pieces?'),
                            style: theme.textTheme.titleMedium,
                          ),
                          Text(
                            context.t('${_chosen.length} of ${widget.wanted} chosen'),
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.qr_code_scanner),
                      tooltip: context.t('Scan'),
                      onPressed:
                          available.isEmpty ? null : () => _scan(available),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: MediaQuery.sizeOf(context).height * 0.44,
                  ),
                  child: Builder(
                    builder: (context) {
                      if (snapshot.connectionState != ConnectionState.done) {
                        return const ListSkeleton(rows: 4, height: 46);
                      }
                      if (snapshot.hasError) {
                        return EmptyState(
                          title: context.t('Could not load pieces'),
                          message: snapshot.error.toString(),
                          isError: true,
                        );
                      }
                      if (available.isEmpty) {
                        return EmptyState(
                          title: context.t('Nothing in stock'),
                          message: context.t('Register the serial numbers on the '
                              'item first, then they can be sold from here.'),
                          icon: Icons.pin_outlined,
                        );
                      }

                      return ListView.builder(
                        shrinkWrap: true,
                        itemCount: available.length,
                        itemBuilder: (context, index) {
                          final row = available[index];
                          final on = _chosen.contains(row.serialNumber);
                          return CheckboxListTile(
                            contentPadding: EdgeInsets.zero,
                            dense: true,
                            value: on,
                            title: Text(row.serialNumber),
                            subtitle: row.warrantyUntil == null
                                ? null
                                : Text(
                                    context.t(
                                      'Warranty to ${Fmt.date(row.warrantyUntil!)}',
                                    ),
                                    style: theme.textTheme.bodySmall,
                                  ),
                            // Once enough are chosen the rest stop being
                            // tappable, so a bill for one handset cannot leave
                            // with two customers' IMEIs on it.
                            onChanged: (!on && _chosen.length >= widget.wanted)
                                ? null
                                : (_) => _toggle(row.serialNumber),
                          );
                        },
                      );
                    },
                  ),
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _chosen.isEmpty
                        ? null
                        : () => Navigator.pop(context, _chosen.toList()),
                    child: Text(context.t('Put on the bill')),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
