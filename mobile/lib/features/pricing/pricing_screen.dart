import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'price_list_screen.dart';
import 'scheme_form_sheet.dart';

/// Price lists and running offers, in one place.
///
/// Two tabs rather than two screens: they answer the same question — why is
/// this line's rate what it is — and a shopkeeper chasing an unexpected total
/// should not have to guess which of two settings pages to open.
class PricingScreen extends ConsumerWidget {
  const PricingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(context.t('Rates & offers')),
          bottom: TabBar(
            tabs: [
              Tab(text: context.t('Price lists')),
              Tab(text: context.t('Offers')),
            ],
          ),
        ),
        body: const TabBarView(children: [_PriceLists(), _Schemes()]),
      ),
    );
  }
}

class _PriceLists extends ConsumerWidget {
  const _PriceLists();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(priceListsProvider);

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'add-price-list',
        onPressed: () => _edit(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.t('New list')),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(priceListsProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load price lists'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(priceListsProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('One price for everyone'),
                  message: context.t(
                      'Make a list if thok and parchoon are different rates. '
                      'Put a customer on it and their bills price themselves.'),
                  icon: Icons.sell_outlined,
                  actionLabel: context.t('New list'),
                  onAction: () => _edit(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 90),
                  children: [
                    for (final list in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _ListCard(list: list),
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}

Future<void> _edit(BuildContext context, WidgetRef ref) async {
  final saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const _PriceListForm(),
  );
  if (saved == true) ref.invalidate(priceListsProvider);
}

class _ListCard extends ConsumerWidget {
  const _ListCard({required this.list});

  final PriceList list;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return AppCard(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => PriceListScreen(list: list)),
      ),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: (list.isDiscount ? AppColors.success : AppColors.primary)
                  .withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              list.isDiscount ? Icons.trending_down : Icons.sell_outlined,
              size: 19,
              color: list.isDiscount ? AppColors.success : AppColors.primary,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        list.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (list.isDefault) ...[
                      const SizedBox(width: 6),
                      const StatusChip('paid', label: 'Default', dense: true),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  list.ruleLabel,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${list.itemCount}',
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
              Text(
                context.t('named rates'),
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
          const SizedBox(width: 4),
          const Icon(Icons.chevron_right, size: 20),
        ],
      ),
    );
  }
}

class _Schemes extends ConsumerWidget {
  const _Schemes();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(schemesProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'add-scheme',
        onPressed: () => showSchemeFormSheet(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.t('New offer')),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(schemesProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load offers'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(schemesProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('No offers running'),
                  message: context.t(
                      'An offer comes off the bill on its own — no one has to '
                      'remember it at the counter.'),
                  icon: Icons.local_offer_outlined,
                  actionLabel: context.t('New offer'),
                  onAction: () => showSchemeFormSheet(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 90),
                  children: [
                    for (final scheme in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _SchemeCard(scheme: scheme, symbol: symbol),
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}

class _SchemeCard extends ConsumerWidget {
  const _SchemeCard({required this.scheme, required this.symbol});

  final DiscountScheme scheme;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final live = scheme.isRunning;

    final conditions = [
      if (scheme.minAmount != null)
        context.t('over ${Fmt.money(scheme.minAmount, symbol: symbol, decimals: false)}'),
      if (scheme.minQty != null) context.t('${trimZeros(scheme.minQty!)}+ units'),
      if (scheme.scope == 'item') context.t('one item'),
      if (scheme.scope == 'category') context.t('one category'),
      if (scheme.scope == 'party') context.t('one customer'),
    ].join('  ·  ');

    return AppCard(
      borderColor: live ? null : theme.colorScheme.outline.withValues(alpha: 0.4),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        scheme.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: live ? null : theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                    const SizedBox(width: 6),
                    StatusChip(
                      live ? 'paid' : 'cancelled',
                      label: live ? 'Running' : 'Not running',
                      dense: true,
                    ),
                  ],
                ),
                const SizedBox(height: 3),
                Text(
                  [scheme.valueLabel, if (conditions.isNotEmpty) conditions]
                      .join('  ·  '),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
                if (scheme.endsOn != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    context.t('until ${Fmt.dateShort(scheme.endsOn)}'),
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
                if (scheme.timesUsed > 0) ...[
                  const SizedBox(height: 2),
                  Text(
                    context.t('taken ${scheme.timesUsed} times'),
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: AppColors.success),
                  ),
                ],
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline, size: 20),
            onPressed: () => _delete(context, ref),
          ),
        ],
      ),
    );
  }

  Future<void> _delete(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Delete this offer?')),
        content: Text(
          context.t('Bills already raised keep the discount they were given.'),
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
    if (confirmed != true || !context.mounted) return;

    try {
      await ref.read(pricingRepositoryProvider).deleteScheme(scheme.id);
      ref.invalidate(schemesProvider);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _PriceListForm extends ConsumerStatefulWidget {
  const _PriceListForm();

  @override
  ConsumerState<_PriceListForm> createState() => _PriceListFormState();
}

class _PriceListFormState extends ConsumerState<_PriceListForm> {
  final _name = TextEditingController();
  final _percent = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  String _basePrice = 'sale';
  bool _isDiscount = true;
  bool _isDefault = false;
  bool _saving = false;

  static const _bases = {
    'sale': 'Selling price',
    'purchase': 'Cost price',
    'mrp': 'MRP',
    'wholesale': 'Wholesale price',
  };

  @override
  void dispose() {
    _name.dispose();
    _percent.dispose();
    super.dispose();
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
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                context.t('New price list'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _name,
                autofocus: true,
                textCapitalization: TextCapitalization.words,
                decoration: InputDecoration(
                  labelText: context.t('Name'),
                  hintText: context.t('Wholesale, Staff, Regular customers'),
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? context.t('Give it a name') : null,
              ),
              const SizedBox(height: 14),
              SegmentedButton<bool>(
                segments: [
                  ButtonSegment(value: true, label: Text(context.t('Cheaper'))),
                  ButtonSegment(value: false, label: Text(context.t('Dearer'))),
                ],
                selected: {_isDiscount},
                onSelectionChanged: (values) =>
                    setState(() => _isDiscount = values.first),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _percent,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('By how much'),
                  suffixText: '%',
                  helperText: context.t(
                      'Leave empty to name rates item by item instead'),
                ),
                validator: (value) {
                  final raw = (value ?? '').trim();
                  if (raw.isEmpty) return null;
                  final percent = num.tryParse(raw);
                  if (percent == null || percent < 0 || percent > 100) {
                    return context.t('0 to 100');
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _basePrice,
                decoration: InputDecoration(labelText: context.t('Worked out from')),
                items: [
                  for (final entry in _bases.entries)
                    DropdownMenuItem(value: entry.key, child: Text(context.t(entry.value))),
                ],
                onChanged: (value) => setState(() => _basePrice = value ?? 'sale'),
              ),
              const SizedBox(height: 4),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _isDefault,
                onChanged: (value) => setState(() => _isDefault = value),
                title: Text(context.t('Use for everyone by default')),
                subtitle: Text(
                  context.t('Customers with no list of their own get this one'),
                ),
              ),
              const SizedBox(height: 8),
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

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);

    // The sign is carried by the Cheaper/Dearer choice rather than by a minus
    // the shopkeeper has to remember to type.
    final magnitude = num.tryParse(_percent.text.trim()) ?? 0;
    final adjust = _isDiscount ? -magnitude : magnitude;

    try {
      await ref.read(pricingRepositoryProvider).createList({
        'name': _name.text.trim(),
        'adjust_percent': adjust,
        'base_price': _basePrice,
        'is_default': _isDefault,
      });
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}
