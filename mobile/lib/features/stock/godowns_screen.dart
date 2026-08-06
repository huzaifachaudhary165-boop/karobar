import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'transfer_stock_sheet.dart';

/// Where stock physically sits.
///
/// A shop with one counter never needs this screen. One with a godown behind
/// the shop, or a second branch, has been guessing until now — the stock figure
/// was a single number with no answer to "which of the two has it".
class GodownsScreen extends ConsumerWidget {
  const GodownsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(godownsProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Stock locations'))),
      floatingActionButton: async.maybeWhen(
        data: (rows) => rows.length >= 2
            ? FloatingActionButton.extended(
                onPressed: () => showTransferStockSheet(context, ref),
                icon: const Icon(Icons.swap_horiz),
                label: Text(context.t('Transfer stock')),
              )
            : null,
        orElse: () => null,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(godownsProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load locations'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(godownsProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('One place for everything'),
                  message: context.t(
                      'Add a location if you keep stock in more than one place — '
                      'a godown, a second shop, a storeroom. Everything you already '
                      'own moves into the first one you create.'),
                  icon: Icons.warehouse_outlined,
                  actionLabel: context.t('Add a location'),
                  onAction: () => _edit(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
                  children: [
                    for (final godown in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _GodownCard(godown: godown, symbol: symbol),
                      ),
                    const SizedBox(height: 6),
                    OutlinedButton.icon(
                      onPressed: () => _edit(context, ref),
                      icon: const Icon(Icons.add),
                      label: Text(context.t('Add a location')),
                    ),
                  ],
                ),
        ),
      ),
    );
  }
}

Future<void> _edit(BuildContext context, WidgetRef ref, {Godown? existing}) async {
  final saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _GodownForm(existing: existing),
  );
  if (saved == true) ref.invalidate(godownsProvider);
}

class _GodownCard extends ConsumerWidget {
  const _GodownCard({required this.godown, required this.symbol});

  final Godown godown;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return AppCard(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => GodownStockScreen(godown: godown)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: AppColors.primary.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(Icons.warehouse_outlined,
                    size: 20, color: AppColors.primary),
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
                            godown.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700),
                          ),
                        ),
                        if (godown.isDefault) ...[
                          const SizedBox(width: 6),
                          const StatusChip('paid', label: 'Default', dense: true),
                        ],
                      ],
                    ),
                    if (godown.address != null && godown.address!.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        godown.address!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ],
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(Icons.more_vert, size: 20),
                onPressed: () => _menu(context, ref),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _Figure(
                label: context.t('Items held'),
                value: '${godown.itemCount}',
              ),
              const SizedBox(width: 20),
              _Figure(
                label: context.t('Stock value'),
                value: Fmt.money(godown.stockValue, symbol: symbol, decimals: false),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _menu(BuildContext context, WidgetRef ref) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: Text(context.t('Edit location')),
              onTap: () => Navigator.pop(sheet, 'edit'),
            ),
            if (!godown.isDefault)
              ListTile(
                leading: const Icon(Icons.star_outline),
                title: Text(context.t('Make this the default')),
                subtitle: Text(context.t('New stock lands here unless told otherwise')),
                onTap: () => Navigator.pop(sheet, 'default'),
              ),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: AppColors.danger),
              title: Text(
                context.t('Delete'),
                style: const TextStyle(color: AppColors.danger),
              ),
              onTap: () => Navigator.pop(sheet, 'delete'),
            ),
          ],
        ),
      ),
    );
    if (!context.mounted || choice == null) return;

    final repository = ref.read(stockRepositoryProvider);
    try {
      switch (choice) {
        case 'edit':
          await _edit(context, ref, existing: godown);
          return;
        case 'default':
          await repository.updateGodown(godown.id, {'is_default': true});
        case 'delete':
          await repository.deleteGodown(godown.id);
      }
      ref.invalidate(godownsProvider);
      if (context.mounted) showSuccess(context, context.t('Saved'));
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Figure extends StatelessWidget {
  const _Figure({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          style: theme.textTheme.labelSmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: theme.textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w800,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }
}

/// What one location is holding right now.
class GodownStockScreen extends ConsumerWidget {
  const GodownStockScreen({super.key, required this.godown});

  final Godown godown;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(godownStockProvider(godown.id));
    final symbol = ref.watch(sessionProvider).symbol;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(godown.name)),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(godownStockProvider(godown.id)),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load stock'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(godownStockProvider(godown.id)),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('Nothing here yet'),
                  message: context.t(
                      'Transfer stock into this location, or record a purchase '
                      'against it.'),
                  icon: Icons.inventory_2_outlined,
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                  itemCount: rows.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, index) {
                    final row = rows[index];
                    return AppCard(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(
                                  row.itemName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.titleSmall
                                      ?.copyWith(fontWeight: FontWeight.w700),
                                ),
                                if (row.sku != null && row.sku!.isNotEmpty)
                                  Text(
                                    row.sku!,
                                    style: theme.textTheme.bodySmall?.copyWith(
                                      color: theme.colorScheme.onSurfaceVariant,
                                    ),
                                  ),
                              ],
                            ),
                          ),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                '${Fmt.qty(row.qty)} ${row.unitLabel}',
                                style: theme.textTheme.titleSmall
                                    ?.copyWith(fontWeight: FontWeight.w800),
                              ),
                              Text(
                                Fmt.money(row.value, symbol: symbol, decimals: false),
                                style: theme.textTheme.labelSmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ),
    );
  }
}

class _GodownForm extends ConsumerStatefulWidget {
  const _GodownForm({this.existing});

  final Godown? existing;

  @override
  ConsumerState<_GodownForm> createState() => _GodownFormState();
}

class _GodownFormState extends ConsumerState<_GodownForm> {
  late final _name = TextEditingController(text: widget.existing?.name ?? '');
  late final _address = TextEditingController(text: widget.existing?.address ?? '');
  late bool _isDefault = widget.existing?.isDefault ?? false;
  final _formKey = GlobalKey<FormState>();
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _address.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              editing ? context.t('Edit location') : context.t('New location'),
              style: Theme.of(context)
                  .textTheme
                  .titleLarge
                  ?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _name,
              autofocus: true,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: context.t('Name'),
                hintText: context.t('Main Store, Godown, Branch 2'),
              ),
              validator: (value) => (value ?? '').trim().isEmpty
                  ? context.t('Give this location a name')
                  : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _address,
              maxLines: 2,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                labelText: context.t('Address'),
                hintText: context.t('Optional'),
              ),
            ),
            const SizedBox(height: 4),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _isDefault,
              onChanged: (value) => setState(() => _isDefault = value),
              title: Text(context.t('Default location')),
              subtitle: Text(
                context.t('New stock lands here when no location is chosen'),
              ),
            ),
            const SizedBox(height: 12),
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
    );
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);

    final repository = ref.read(stockRepositoryProvider);
    final body = {
      'name': _name.text.trim(),
      'address': _address.text.trim(),
      'is_default': _isDefault,
    };

    try {
      if (widget.existing == null) {
        await repository.createGodown(body);
      } else {
        await repository.updateGodown(widget.existing!.id, body);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}
