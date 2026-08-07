import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// The rates named on one price list.
///
/// Only the exceptions live here. The list's own rule already covers the whole
/// catalogue, so an item appears on this screen precisely because it does not
/// follow that rule — "everything at 8% off, except sugar which is fixed".
class PriceListScreen extends ConsumerStatefulWidget {
  const PriceListScreen({super.key, required this.list});

  final PriceList list;

  @override
  ConsumerState<PriceListScreen> createState() => _PriceListScreenState();
}

class _PriceListScreenState extends ConsumerState<PriceListScreen> {
  @override
  Widget build(BuildContext context) {
    final async = ref.watch(priceEntriesProvider(widget.list.id));
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.list.name),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: _deleteList,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addRate,
        icon: const Icon(Icons.add),
        label: Text(context.t('Name a rate')),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(priceEntriesProvider(widget.list.id)),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load rates'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(priceEntriesProvider(widget.list.id)),
          ),
          data: (rows) => ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 90),
            children: [
              AppCard(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                child: Row(
                  children: [
                    const Icon(Icons.rule, size: 18),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        context.t('Everything else: ${widget.list.ruleLabel}'),
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  ],
                ),
              ),
              if (rows.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 40),
                  child: EmptyState(
                    title: context.t('No exceptions'),
                    message: context.t(
                        'Every item follows the rule above. Name a rate here for '
                        'anything that should not.'),
                    icon: Icons.price_change_outlined,
                  ),
                )
              else ...[
                SectionHeader(context.t('Named rates (${rows.length})')),
                for (final entry in rows)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _EntryRow(
                      entry: entry,
                      symbol: symbol,
                      onEdit: () => _addRate(existing: entry),
                      onRemove: () => _removeRate(entry),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _addRate({PriceEntry? existing}) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RateSheet(listId: widget.list.id, existing: existing),
    );
    if (saved == true) {
      ref.invalidate(priceEntriesProvider(widget.list.id));
      ref.invalidate(priceListsProvider);
    }
  }

  Future<void> _removeRate(PriceEntry entry) async {
    try {
      await ref
          .read(pricingRepositoryProvider)
          .removeEntry(widget.list.id, entry.itemId);
      ref.invalidate(priceEntriesProvider(widget.list.id));
      ref.invalidate(priceListsProvider);
      if (mounted) {
        showSuccess(context, context.t('${entry.itemName} now follows the rule'));
      }
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  Future<void> _deleteList() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Delete this price list?')),
        content: Text(
          context.t('Customers on it go back to your ordinary prices. Bills '
              'already raised keep the rates they were given.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialog, false),
            child: Text(context.t('Cancel')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialog, true),
            child: Text(context.t('Delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    try {
      await ref.read(pricingRepositoryProvider).deleteList(widget.list.id);
      ref.invalidate(priceListsProvider);
      if (mounted) Navigator.pop(context);
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }
}

class _EntryRow extends StatelessWidget {
  const _EntryRow({
    required this.entry,
    required this.symbol,
    required this.onEdit,
    required this.onRemove,
  });

  final PriceEntry entry;
  final String symbol;
  final VoidCallback onEdit;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cheaper = entry.price < entry.salePrice;

    return AppCard(
      onTap: onEdit,
      padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  entry.itemName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  [
                    context.t('normally '
                        '${Fmt.money(entry.salePrice, symbol: symbol, decimals: false)}'),
                    if (entry.minQty != null)
                      context.t('from ${trimZeros(entry.minQty!)} ${entry.unitLabel}'),
                  ].join('  ·  '),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          Text(
            Fmt.money(entry.price, symbol: symbol, decimals: false),
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w800,
              color: cheaper ? AppColors.success : null,
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close, size: 18),
            visualDensity: VisualDensity.compact,
            onPressed: onRemove,
          ),
        ],
      ),
    );
  }
}

class _RateSheet extends ConsumerStatefulWidget {
  const _RateSheet({required this.listId, this.existing});

  final String listId;
  final PriceEntry? existing;

  @override
  ConsumerState<_RateSheet> createState() => _RateSheetState();
}

class _RateSheetState extends ConsumerState<_RateSheet> {
  late final _price = TextEditingController(
    text: widget.existing == null ? '' : trimZeros(widget.existing!.price),
  );
  late final _minQty = TextEditingController(
    text: widget.existing?.minQty == null ? '' : trimZeros(widget.existing!.minQty!),
  );
  final _search = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  Item? _item;
  List<Item> _results = const [];
  bool _saving = false;

  @override
  void dispose() {
    _price.dispose();
    _minQty.dispose();
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final editing = widget.existing != null;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                editing ? widget.existing!.itemName : context.t('Name a rate'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),
              if (!editing) ...[
                TextField(
                  controller: _search,
                  decoration: InputDecoration(
                    labelText: context.t('Item'),
                    prefixIcon: const Icon(Icons.search),
                  ),
                  onChanged: _searchItems,
                ),
                if (_results.isNotEmpty)
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 170),
                    child: ListView(
                      shrinkWrap: true,
                      children: [
                        for (final item in _results)
                          ListTile(
                            dense: true,
                            title: Text(item.name,
                                maxLines: 1, overflow: TextOverflow.ellipsis),
                            subtitle: Text(Fmt.money(item.salePrice, decimals: false)),
                            onTap: () {
                              _search.text = item.name;
                              setState(() {
                                _item = item;
                                _results = const [];
                              });
                            },
                          ),
                      ],
                    ),
                  ),
                const SizedBox(height: 12),
              ],
              TextFormField(
                controller: _price,
                autofocus: editing,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(labelText: context.t('Rate on this list')),
                validator: (value) {
                  final price = num.tryParse((value ?? '').trim());
                  return price == null || price < 0 ? context.t('Enter a rate') : null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _minQty,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('Only from this quantity'),
                  helperText: context.t('Leave empty for any quantity'),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Save')),
              ),
            ],
          ),
        ),
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

  Future<void> _save() async {
    final itemId = widget.existing?.itemId ?? _item?.id;
    if (itemId == null) {
      showError(context, context.t('Choose an item first'));
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _saving = true);
    try {
      await ref.read(pricingRepositoryProvider).setEntry(
            widget.listId,
            itemId,
            num.parse(_price.text.trim()),
            minQty: num.tryParse(_minQty.text.trim()),
          );
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}
