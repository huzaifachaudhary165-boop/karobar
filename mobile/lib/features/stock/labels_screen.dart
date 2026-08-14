import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/share_bytes.dart';
import '../../core/theme/app_colors.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Print barcode stickers for shelf edges and packets.
///
/// The sheet is built on the server and handed over as HTML, because every
/// Android phone can print HTML through the system dialog and hardly any shop
/// has a label printer paired to the counter phone. A shop that does have one
/// picks a roll size and the same page prints one sticker at a time.
class LabelsScreen extends ConsumerStatefulWidget {
  const LabelsScreen({super.key, this.initialItem});

  final Item? initialItem;

  @override
  ConsumerState<LabelsScreen> createState() => _LabelsScreenState();
}

class _LabelsScreenState extends ConsumerState<LabelsScreen> {
  final _search = TextEditingController();
  final _chosen = <String, ({Item item, int qty})>{};

  String _size = 'a4_65';
  int _startAt = 1;
  bool _showName = true;
  bool _showPrice = true;
  bool _showMrp = false;
  bool _showCode = true;
  bool _showShop = false;
  bool _busy = false;

  List<Item> _results = const [];

  @override
  void initState() {
    super.initState();
    final item = widget.initialItem;
    if (item != null) _chosen[item.id] = (item: item, qty: 1);
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  int get _total => _chosen.values.fold(0, (sum, row) => sum + row.qty);

  @override
  Widget build(BuildContext context) {
    final sizes = ref.watch(labelSizesProvider);

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Barcode labels'))),
      bottomNavigationBar: _chosen.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: FilledButton.icon(
                  onPressed: _busy ? null : _print,
                  icon: _busy
                      ? const SizedBox(
                          width: 16, height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.print_outlined),
                  label: Text(
                    context.t('Print $_total ${_total == 1 ? 'label' : 'labels'}'),
                  ),
                ),
              ),
            ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
        children: [
          TextField(
            controller: _search,
            decoration: InputDecoration(
              labelText: context.t('Add an item'),
              hintText: context.t('Search by name, code or barcode'),
              prefixIcon: const Icon(Icons.search),
            ),
            onChanged: _searchItems,
          ),
          if (_results.isNotEmpty)
            Card(
              margin: const EdgeInsets.only(top: 8),
              child: Column(
                children: [
                  for (final item in _results.take(6))
                    ListTile(
                      dense: true,
                      title: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Text(
                        item.barcode?.isNotEmpty == true
                            ? item.barcode!
                            : context.t('No barcode yet'),
                        style: TextStyle(
                          color: item.barcode?.isNotEmpty == true
                              ? null
                              : AppColors.warning,
                        ),
                      ),
                      trailing: const Icon(Icons.add),
                      onTap: () => _add(item),
                    ),
                ],
              ),
            ),

          if (_chosen.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 40),
              child: EmptyState(
                title: context.t('Nothing chosen yet'),
                message: context.t(
                    'Search for the items you want stickers for, then set how '
                    'many of each.'),
                icon: Icons.qr_code_2_outlined,
              ),
            )
          else ...[
            SectionHeader(context.t('Printing (${_chosen.length})')),
            for (final row in _chosen.values)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _ChosenRow(
                  item: row.item,
                  qty: row.qty,
                  onChanged: (qty) => setState(() {
                    if (qty <= 0) {
                      _chosen.remove(row.item.id);
                    } else {
                      _chosen[row.item.id] = (item: row.item, qty: qty);
                    }
                  }),
                  onAssignBarcode: () => _assignBarcode(row.item),
                ),
              ),

            SectionHeader(context.t('Sticker paper')),
            sizes.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(16),
                child: LinearProgressIndicator(),
              ),
              error: (error, _) => Text(error.toString()),
              data: (rows) => Column(
                children: [
                  DropdownButtonFormField<String>(
                    initialValue: rows.any((s) => s.key == _size) ? _size : rows.first.key,
                    decoration: InputDecoration(labelText: context.t('Size')),
                    items: [
                      for (final size in rows)
                        DropdownMenuItem(value: size.key, child: Text(size.name)),
                    ],
                    onChanged: (value) => setState(() {
                      _size = value ?? _size;
                      _startAt = 1;
                    }),
                  ),
                  // Only a sheet has positions to skip; a roll feeds one at a
                  // time and starting partway through means nothing.
                  if (rows.any((s) => s.key == _size && !s.isRoll)) ...[
                    const SizedBox(height: 12),
                    _StartAtField(
                      perSheet: rows.firstWhere((s) => s.key == _size).perSheet,
                      value: _startAt,
                      onChanged: (value) => setState(() => _startAt = value),
                    ),
                  ],
                ],
              ),
            ),

            SectionHeader(context.t('What goes on the sticker')),
            _Toggle(
              label: context.t('Item name'),
              value: _showName,
              onChanged: (v) => setState(() => _showName = v),
            ),
            _Toggle(
              label: context.t('Selling price'),
              value: _showPrice,
              onChanged: (v) => setState(() => _showPrice = v),
            ),
            _Toggle(
              label: context.t('MRP'),
              value: _showMrp,
              onChanged: (v) => setState(() => _showMrp = v),
            ),
            _Toggle(
              label: context.t('Barcode number'),
              value: _showCode,
              onChanged: (v) => setState(() => _showCode = v),
            ),
            _Toggle(
              label: context.t('Shop name'),
              value: _showShop,
              onChanged: (v) => setState(() => _showShop = v),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _searchItems(String query) async {
    if (query.trim().length < 2) {
      setState(() => _results = const []);
      return;
    }
    try {
      final found = await ref.read(itemRepositoryProvider).search(query);
      if (mounted) setState(() => _results = found);
    } catch (_) {
      if (mounted) setState(() => _results = const []);
    }
  }

  void _add(Item item) {
    setState(() {
      final existing = _chosen[item.id];
      _chosen[item.id] = (item: item, qty: (existing?.qty ?? 0) + 1);
      _results = const [];
      _search.clear();
    });
  }

  Future<void> _assignBarcode(Item item) async {
    try {
      final code = await ref.read(stockRepositoryProvider).assignBarcode(item.id);
      if (!mounted) return;
      // Rebuild the row from the item it now is, so the warning clears.
      final refreshed = await ref.read(itemRepositoryProvider).get(item.id);
      if (!mounted) return;
      setState(() {
        final existing = _chosen[item.id];
        _chosen[item.id] = (item: refreshed, qty: existing?.qty ?? 1);
      });
      ref.invalidate(itemsProvider);
      showSuccess(context, context.t('Barcode $code assigned'));
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  Future<void> _print() async {
    setState(() => _busy = true);
    try {
      final html = await ref.read(stockRepositoryProvider).labelSheet(
            items: [
              for (final row in _chosen.values) (itemId: row.item.id, qty: row.qty),
            ],
            size: _size,
            showName: _showName,
            showPrice: _showPrice,
            showMrp: _showMrp,
            showCode: _showCode,
            showShop: _showShop,
            startAt: _startAt,
          );

      // Shared rather than shown in-app: the share sheet is where the printer,
      // the PDF writer and WhatsApp all already live, and a preview the
      // shopkeeper cannot print from is not worth the screen.
      if (!mounted) return;
      await shareDocument(
        html,
        filename: 'karobar-labels.html',
        mimeType: 'text/html',
        subject: 'Barcode labels',
      );
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _ChosenRow extends StatelessWidget {
  const _ChosenRow({
    required this.item,
    required this.qty,
    required this.onChanged,
    required this.onAssignBarcode,
  });

  final Item item;
  final int qty;
  final ValueChanged<int> onChanged;
  final VoidCallback onAssignBarcode;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasCode = item.barcode?.isNotEmpty == true;

    return AppCard(
      padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      item.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    if (hasCode)
                      Text(
                        item.barcode!,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                          fontFeatures: const [FontFeature.tabularFigures()],
                        ),
                      ),
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(Icons.remove_circle_outline, size: 22),
                onPressed: () => onChanged(qty - 1),
              ),
              SizedBox(
                width: 28,
                child: Text(
                  '$qty',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.add_circle_outline, size: 22),
                onPressed: () => onChanged(qty + 1),
              ),
            ],
          ),
          // An item with no code still prints — the name and price are worth
          // having on the shelf — but the sticker says so, and giving it one
          // here is a single tap rather than a trip to the item screen.
          if (!hasCode)
            Padding(
              padding: const EdgeInsets.only(top: 6, right: 8),
              child: Row(
                children: [
                  const Icon(Icons.info_outline, size: 15, color: AppColors.warning),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      context.t('No barcode — the sticker will say so'),
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: AppColors.warning),
                    ),
                  ),
                  TextButton(
                    onPressed: onAssignBarcode,
                    child: Text(context.t('Give it one')),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _StartAtField extends StatelessWidget {
  const _StartAtField({
    required this.perSheet,
    required this.value,
    required this.onChanged,
  });

  final int perSheet;
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            context.t('Start at sticker'),
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ),
        IconButton(
          icon: const Icon(Icons.remove_circle_outline, size: 22),
          onPressed: value > 1 ? () => onChanged(value - 1) : null,
        ),
        SizedBox(
          width: 32,
          child: Text(
            '$value',
            textAlign: TextAlign.center,
            style: Theme.of(context)
                .textTheme
                .titleSmall
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
        ),
        IconButton(
          icon: const Icon(Icons.add_circle_outline, size: 22),
          onPressed: value < perSheet ? () => onChanged(value + 1) : null,
        ),
      ],
    );
  }
}

class _Toggle extends StatelessWidget {
  const _Toggle({required this.label, required this.value, required this.onChanged});

  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      dense: true,
      title: Text(label),
      value: value,
      onChanged: onChanged,
    );
  }
}
