import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/barcode_sheet.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Every individual piece of an item, by its own number.
///
/// A mobile shop with six identical handsets does not have six of one thing —
/// it has six things, and when a customer comes back with a fault the only
/// question that matters is which one they were sold and whether it is still in
/// warranty. A stock figure of "6" cannot answer either.
Future<void> showSerialsSheet(
  BuildContext context, {
  required String itemId,
  required String itemName,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _SerialsSheet(itemId: itemId, itemName: itemName),
  );
}

class _SerialsSheet extends ConsumerStatefulWidget {
  const _SerialsSheet({required this.itemId, required this.itemName});

  final String itemId;
  final String itemName;

  @override
  ConsumerState<_SerialsSheet> createState() => _SerialsSheetState();
}

class _SerialsSheetState extends ConsumerState<_SerialsSheet> {
  late Future<List<ItemSerial>> _future = _load();

  Future<List<ItemSerial>> _load() =>
      ref.read(stockRepositoryProvider).serials(widget.itemId);

  void _reload() => setState(() => _future = _load());

  Future<void> _add() async {
    final added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SerialEntry(itemId: widget.itemId),
    );
    if (added == true) _reload();
  }

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
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        context.t('Serial numbers'),
                        style: theme.textTheme.titleMedium,
                      ),
                      Text(
                        widget.itemName,
                        style: theme.textTheme.bodySmall,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                FilledButton.icon(
                  onPressed: _add,
                  icon: const Icon(Icons.add, size: 18),
                  label: Text(context.t('Add')),
                ),
              ],
            ),
            const SizedBox(height: 14),
            ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(context).height * 0.5,
              ),
              child: FutureBuilder<List<ItemSerial>>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const ListSkeleton(rows: 3, height: 56);
                  }
                  if (snapshot.hasError) {
                    return EmptyState(
                      title: context.t('Could not load serial numbers'),
                      message: snapshot.error.toString(),
                      isError: true,
                      actionLabel: context.t('Retry'),
                      onAction: _reload,
                    );
                  }

                  final rows = snapshot.data ?? const <ItemSerial>[];
                  if (rows.isEmpty) {
                    return EmptyState(
                      title: context.t('No pieces registered yet'),
                      message: context.t('Add the IMEI or serial of each piece as '
                          'it comes in. Selling one then records which piece went '
                          'to which customer.'),
                      icon: Icons.pin_outlined,
                    );
                  }

                  return ListView.separated(
                    shrinkWrap: true,
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) => _SerialRow(rows[index]),
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

class _SerialRow extends StatelessWidget {
  const _SerialRow(this.serial);

  final ItemSerial serial;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final (status, label) = switch (serial.status) {
      'sold' => ('paid', context.t('Sold')),
      'damaged' => ('overdue', context.t('Damaged')),
      'returned' => ('partial', context.t('Returned')),
      _ => ('draft', context.t('In stock')),
    };

    return ListTile(
      contentPadding: EdgeInsets.zero,
      dense: true,
      title: Text(serial.serialNumber, style: theme.textTheme.bodyMedium),
      subtitle: serial.warrantyUntil == null
          ? null
          : Text(
              serial.inWarranty
                  ? context.t('In warranty until ${Fmt.date(serial.warrantyUntil!)}')
                  : context.t('Warranty ended ${Fmt.date(serial.warrantyUntil!)}'),
              style: theme.textTheme.bodySmall,
            ),
      trailing: StatusChip(status, label: label, dense: true),
    );
  }
}

class _SerialEntry extends ConsumerStatefulWidget {
  const _SerialEntry({required this.itemId});

  final String itemId;

  @override
  ConsumerState<_SerialEntry> createState() => _SerialEntryState();
}

class _SerialEntryState extends ConsumerState<_SerialEntry> {
  final _typed = TextEditingController();
  final _cost = TextEditingController();
  final _warranty = TextEditingController();
  final _collected = <String>[];

  bool _busy = false;

  @override
  void dispose() {
    for (final field in [_typed, _cost, _warranty]) {
      field.dispose();
    }
    super.dispose();
  }

  /// Accepts a whole box at once.
  ///
  /// Serials arrive on a delivery note as a column, and a shopkeeper pasting
  /// twenty of them should not have to press Add twenty times. Anything that
  /// separates lines or values in the real world separates them here.
  void _take(String raw) {
    final parts = raw
        .split(RegExp(r'[\s,;]+'))
        .map((part) => part.trim())
        .where((part) => part.isNotEmpty);

    setState(() {
      for (final part in parts) {
        // The same handset entered twice is one handset, and the server would
        // refuse the second anyway — better to say so before it is sent.
        if (!_collected.contains(part)) _collected.add(part);
      }
      _typed.clear();
    });
  }

  Future<void> _scan() async {
    while (true) {
      if (!mounted) return;
      final code = await scanBarcode(context);
      if (code == null || !mounted) return;
      _take(code);
    }
  }

  Future<void> _save() async {
    _take(_typed.text);
    if (_collected.isEmpty) {
      showError(context, 'Add at least one serial number.');
      return;
    }

    setState(() => _busy = true);
    try {
      final result = await ref.read(stockRepositoryProvider).addSerials(
            itemId: widget.itemId,
            serials: _collected,
            purchasePrice: num.tryParse(_cost.text.trim()),
            warrantyMonths: int.tryParse(_warranty.text.trim()),
          );
      if (!mounted) return;

      // Duplicates are not a failure — the rest went in. Saying which ones were
      // already registered is more use than a count that hides them.
      if (result.duplicates.isNotEmpty) {
        showError(
          context,
          'Already registered: ${result.duplicates.take(5).join(', ')}'
          '${result.duplicates.length > 5 ? ' and ${result.duplicates.length - 5} more' : ''}',
        );
      } else {
        showSuccess(context, '${result.addedCount} added.');
      }
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(context.t('Add serial numbers'), style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(
            context.t('Scan them, or paste the whole list from the delivery note.'),
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _typed,
            autofocus: true,
            maxLines: null,
            textInputAction: TextInputAction.done,
            onSubmitted: _take,
            decoration: InputDecoration(
              labelText: context.t('Serial / IMEI'),
              prefixIcon: const Icon(Icons.pin_outlined),
              suffixIcon: IconButton(
                icon: const Icon(Icons.qr_code_scanner),
                tooltip: context.t('Scan'),
                onPressed: _scan,
              ),
            ),
          ),
          if (_collected.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              context.t('${_collected.length} ready to add'),
              style: theme.textTheme.labelMedium,
            ),
            const SizedBox(height: 6),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 130),
              child: SingleChildScrollView(
                child: Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final serial in _collected)
                      InputChip(
                        label: Text(serial),
                        onDeleted: () => setState(() => _collected.remove(serial)),
                      ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _cost,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(labelText: context.t('Cost each')),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _warranty,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText: context.t('Warranty'),
                    suffixText: context.t('months'),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _busy ? null : _save,
              child: _busy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : Text(context.t('Register')),
            ),
          ),
        ],
      ),
    );
  }
}
