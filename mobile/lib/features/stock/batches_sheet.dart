import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// The batches an item has arrived in, and a way to add another.
///
/// A chemist buying Panadol twice buys two different things: the strip expiring
/// in March and the strip expiring in November. Kept as one stock figure, the
/// March strips sit at the back until they are worthless and the shop finds out
/// by throwing them away.
Future<void> showBatchesSheet(
  BuildContext context, {
  required String itemId,
  required String itemName,
  bool withExpiry = true,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _BatchesSheet(
      itemId: itemId,
      itemName: itemName,
      withExpiry: withExpiry,
    ),
  );
}

class _BatchesSheet extends ConsumerStatefulWidget {
  const _BatchesSheet({
    required this.itemId,
    required this.itemName,
    required this.withExpiry,
  });

  final String itemId;
  final String itemName;
  final bool withExpiry;

  @override
  ConsumerState<_BatchesSheet> createState() => _BatchesSheetState();
}

class _BatchesSheetState extends ConsumerState<_BatchesSheet> {
  late Future<List<ItemBatch>> _future = _load();

  Future<List<ItemBatch>> _load() =>
      ref.read(stockRepositoryProvider).batches(widget.itemId);

  void _reload() => setState(() => _future = _load());

  Future<void> _add() async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _BatchForm(
        itemId: widget.itemId,
        withExpiry: widget.withExpiry,
      ),
    );
    if (saved == true) _reload();
  }

  Future<void> _remove(ItemBatch batch) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('Remove batch ${batch.batchNumber}?')),
        content: Text(
          context.t('The stock in it goes with it. Do this only if the batch '
              'was entered by mistake.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(context.t('Keep')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(context.t('Remove')),
          ),
        ],
      ),
    );
    if (ok != true) return;

    try {
      await ref.read(stockRepositoryProvider).deleteBatch(batch.id);
      if (!mounted) return;
      _reload();
    } catch (error) {
      if (mounted) showError(context, error);
    }
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
                      Text(context.t('Batches'), style: theme.textTheme.titleMedium),
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
              child: FutureBuilder<List<ItemBatch>>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const ListSkeleton(rows: 3, height: 62);
                  }
                  if (snapshot.hasError) {
                    return EmptyState(
                      title: context.t('Could not load batches'),
                      message: snapshot.error.toString(),
                      isError: true,
                      actionLabel: context.t('Retry'),
                      onAction: _reload,
                    );
                  }

                  final rows = snapshot.data ?? const <ItemBatch>[];
                  if (rows.isEmpty) {
                    return EmptyState(
                      title: context.t('No batches yet'),
                      message: context.t('Add one for each lot you receive, with '
                          'its own expiry date. Selling always takes from the '
                          'batch expiring first.'),
                      icon: Icons.inventory_2_outlined,
                    );
                  }

                  return ListView.separated(
                    shrinkWrap: true,
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, index) => _BatchRow(
                      batch: rows[index],
                      onRemove: () => _remove(rows[index]),
                    ),
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

class _BatchRow extends StatelessWidget {
  const _BatchRow({required this.batch, required this.onRemove});

  final ItemBatch batch;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Expired reads as overdue and near-expiry as partial, so this list borrows
    // the colours a shopkeeper already reads on invoices: red is money already
    // lost, amber is money about to be.
    final (status, label) = switch (batch) {
      _ when batch.isExpired => ('overdue', context.t('Expired')),
      _ when batch.isExpiringSoon => (
          'partial',
          context.t('${batch.daysToExpiry} days left')
        ),
      _ => (null, null),
    };

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        batch.batchNumber,
                        style: theme.textTheme.titleSmall,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (status != null) ...[
                      const SizedBox(width: 8),
                      StatusChip(status, label: label, dense: true),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  [
                    '${Fmt.qty(batch.qty)} in stock',
                    if (batch.expiryDate != null)
                      'expires ${Fmt.date(batch.expiryDate!)}',
                  ].join(' · '),
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline, size: 20),
            tooltip: context.t('Remove'),
            onPressed: onRemove,
          ),
        ],
      ),
    );
  }
}

class _BatchForm extends ConsumerStatefulWidget {
  const _BatchForm({required this.itemId, required this.withExpiry});

  final String itemId;
  final bool withExpiry;

  @override
  ConsumerState<_BatchForm> createState() => _BatchFormState();
}

class _BatchFormState extends ConsumerState<_BatchForm> {
  final _formKey = GlobalKey<FormState>();
  final _number = TextEditingController();
  final _qty = TextEditingController();
  final _cost = TextEditingController();
  final _mrp = TextEditingController();

  DateTime? _expiry;
  bool _busy = false;

  @override
  void dispose() {
    for (final field in [_number, _qty, _cost, _mrp]) {
      field.dispose();
    }
    super.dispose();
  }

  Future<void> _pickExpiry() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _expiry ?? DateTime(now.year + 1, now.month, now.day),
      // A batch already on the shelf can be past its date — that is exactly the
      // stock this feature exists to surface, so the picker must allow it.
      firstDate: DateTime(now.year - 5),
      lastDate: DateTime(now.year + 15),
    );
    if (picked != null) setState(() => _expiry = picked);
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    if (widget.withExpiry && _expiry == null) {
      showError(context, 'Choose the expiry date for this batch.');
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(stockRepositoryProvider).createBatch({
        'item_id': widget.itemId,
        'batch_number': _number.text.trim(),
        'qty': num.tryParse(_qty.text.trim()) ?? 0,
        if (_expiry != null) 'expiry_date': Fmt.iso(_expiry!),
        if (_cost.text.trim().isNotEmpty)
          'purchase_price': num.tryParse(_cost.text.trim()),
        if (_mrp.text.trim().isNotEmpty) 'mrp': num.tryParse(_mrp.text.trim()),
      });
      if (!mounted) return;
      Navigator.pop(context, true);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              context.t('New batch'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _number,
              autofocus: true,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                labelText: context.t('Batch number *'),
                helperText: context.t('Printed on the box or strip'),
              ),
              validator: (value) => (value == null || value.trim().isEmpty)
                  ? 'Batch number is required'
                  : null,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _qty,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(labelText: context.t('Quantity *')),
                    validator: (value) {
                      final parsed = num.tryParse(value?.trim() ?? '');
                      return (parsed == null || parsed <= 0) ? 'Required' : null;
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: InkWell(
                    onTap: _pickExpiry,
                    child: InputDecorator(
                      decoration: InputDecoration(
                        labelText: context.t(
                          widget.withExpiry ? 'Expires on *' : 'Expires on',
                        ),
                        suffixIcon: const Icon(Icons.calendar_today, size: 18),
                      ),
                      child: Text(
                        _expiry == null ? '—' : Fmt.date(_expiry!),
                      ),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _cost,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(labelText: context.t('Cost price')),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: _mrp,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(labelText: context.t('MRP')),
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
                    : Text(context.t('Add batch')),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
