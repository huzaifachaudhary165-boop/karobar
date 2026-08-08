import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/env.dart';
import '../../core/l10n/strings.dart';
import '../../core/network/api_exception.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/barcode_sheet.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

class ItemsScreen extends ConsumerStatefulWidget {
  const ItemsScreen({super.key});

  @override
  ConsumerState<ItemsScreen> createState() => _ItemsScreenState();
}

class _ItemsScreenState extends ConsumerState<ItemsScreen> {
  final _controller = TextEditingController();
  Timer? _debounce;

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(Env.searchDebounce, () {
      ref.read(itemSearchProvider.notifier).state = value.trim();
    });
  }

  /// Scan → open that item's page. If the code isn't on file yet, offer to
  /// create the item with the barcode already filled in — that's the moment a
  /// shopkeeper is holding the product and most likely to add it.
  Future<void> _scanAndOpen() async {
    final code = await scanBarcode(context);
    if (code == null || !mounted) return;

    try {
      final item = await ref.read(itemRepositoryProvider).byBarcode(code);
      if (!mounted) return;
      context.goNamed(Routes.itemForm, queryParameters: {'id': item.id});
    } on ApiException catch (error) {
      if (!mounted) return;
      if (!error.isNotFound) {
        showError(context, error);
        return;
      }

      final add = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(context.t('New barcode')),
          content: Text('No item has the code $code yet. Add it now?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: Text(context.t('Not now')),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: Text(context.t('Add item')),
            ),
          ],
        ),
      );
      if (add == true && mounted) {
        context.goNamed(Routes.itemForm, queryParameters: {'barcode': code});
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(itemsProvider);
    final summary = ref.watch(stockSummaryProvider);
    final filter = ref.watch(itemFilterProvider);
    final symbol = ref.watch(sessionProvider).symbol;
    final strings = context.s;

    return Scaffold(
      appBar: AppBar(
        title: Text(strings.get('items')),
        actions: [
          IconButton(
            icon: const Icon(Icons.qr_code_scanner),
            tooltip: context.t('Scan a barcode'),
            onPressed: _scanAndOpen,
          ),
          IconButton(
            icon: const Icon(Icons.add_box_outlined),
            tooltip: strings.get('add_item'),
            onPressed: () => context.goNamed(Routes.itemForm),
          ),
        ],
      ),
      body: Column(
        children: [
          // valueOrNull so these two tiles stay put during a refresh instead of
          // collapsing and pushing the whole list up, then dropping it back.
          if (summary.valueOrNull case final data?)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Row(
                children: [
                  Expanded(
                    child: StatTile(
                      label: strings.get('stock_value'),
                      value: Fmt.compactMoney(asNumOrNull(data['total_stock_value']),
                          symbol: symbol),
                      icon: Icons.inventory_2_outlined,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: StatTile(
                      label: strings.get('low_stock'),
                      value: '${data['low_stock_count'] ?? 0}',
                      icon: Icons.warning_amber_rounded,
                      accent: AppColors.warning,
                      onTap: () =>
                          ref.read(itemFilterProvider.notifier).state = 'low_stock',
                    ),
                  ),
                ],
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
            child: TextField(
              controller: _controller,
              onChanged: _onSearchChanged,
              decoration: InputDecoration(
                hintText: context.t('Search by name, SKU or barcode'),
                prefixIcon: const Icon(Icons.search),
              ),
            ),
          ),
          SizedBox(
            height: 46,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final entry in {
                  'all': 'All items',
                  'low_stock': strings.get('low_stock'),
                  'retired': 'Retired',
                }.entries) ...[
                  ChoiceChip(
                    label: Text(entry.value),
                    selected: filter == entry.key,
                    showCheckmark: false,
                    onSelected: (_) =>
                        ref.read(itemFilterProvider.notifier).state = entry.key,
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          Expanded(
            child: async.when(
              loading: () => const ListSkeleton(),
              error: (error, _) => EmptyState(
                title: 'Could not load items',
                message: error.toString(),
                isError: true,
                actionLabel: strings.get('retry'),
                onAction: () => ref.invalidate(itemsProvider),
              ),
              data: (page) => page.isEmpty
                  ? EmptyState(
                      title: strings.get('no_data'),
                      message: 'Add the products you buy and sell.',
                      icon: Icons.inventory_2_outlined,
                      actionLabel: strings.get('add_item'),
                      onAction: () => context.goNamed(Routes.itemForm),
                    )
                  : RefreshIndicator(
                      onRefresh: () async {
                        ref.invalidate(itemsProvider);
                        ref.invalidate(stockSummaryProvider);
                      },
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                        itemCount: page.items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (_, index) =>
                            _ItemRow(item: page.items[index], symbol: symbol),
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ItemRow extends StatelessWidget {
  const _ItemRow({required this.item, required this.symbol});

  final Item item;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final stockColor = item.isOutOfStock
        ? AppColors.danger
        : item.isLowStock
            ? AppColors.warning
            : AppColors.success;

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () => context.goNamed(Routes.itemForm, queryParameters: {'id': item.id}),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: AppColors.softTint(AppColors.primary, Theme.of(context).brightness),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(Icons.inventory_2_outlined,
                size: 20, color: AppColors.primaryDarker),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  item.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 3),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(
                        color: stockColor.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(5),
                      ),
                      child: Text(
                        item.trackInventory ? item.stockLabel : 'Service',
                        style: TextStyle(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w700,
                          color: stockColor,
                        ),
                      ),
                    ),
                    if (item.taxRate > 0) ...[
                      const SizedBox(width: 6),
                      Text(
                        'Tax ${Fmt.qty(item.taxRate)}%',
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              MoneyText(
                item.salePrice,
                symbol: symbol,
                decimals: false,
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              Text(
                'Cost ${Fmt.money(item.purchasePrice, symbol: symbol, decimals: false)}',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
