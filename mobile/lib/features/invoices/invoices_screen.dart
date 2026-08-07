import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/env.dart';
import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/document_types.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

class InvoicesScreen extends ConsumerStatefulWidget {
  const InvoicesScreen({super.key});

  @override
  ConsumerState<InvoicesScreen> createState() => _InvoicesScreenState();
}

class _InvoicesScreenState extends ConsumerState<InvoicesScreen> {
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
      ref.read(voucherSearchProvider.notifier).state = value.trim();
    });
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(vouchersProvider);
    final type = ref.watch(voucherTypeProvider);
    final filter = ref.watch(voucherFilterProvider);
    final symbol = ref.watch(sessionProvider).symbol;
    final strings = context.s;

    return Scaffold(
      appBar: AppBar(
        title: Text(strings.get('invoices')),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            tooltip: DocumentType.of(type).newLabel,
            onPressed: () => context.goNamed(
              Routes.invoiceForm,
              queryParameters: {'type': type},
            ),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: TabBarSelector(
            value: type,
            options: {
              for (final doc in DocumentType.listed) doc.key: doc.plural,
            },
            onChanged: (value) => ref.read(voucherTypeProvider.notifier).state = value,
          ),
        ),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
            child: TextField(
              controller: _controller,
              onChanged: _onSearchChanged,
              decoration: InputDecoration(
                hintText: context.t('Search by number or customer'),
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
                  'all': 'All',
                  'unpaid': 'Unpaid',
                  'overdue': 'Overdue',
                }.entries) ...[
                  ChoiceChip(
                    label: Text(entry.value),
                    selected: filter == entry.key,
                    showCheckmark: false,
                    onSelected: (_) =>
                        ref.read(voucherFilterProvider.notifier).state = entry.key,
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
                title: 'Could not load invoices',
                message: error.toString(),
                isError: true,
                actionLabel: strings.get('retry'),
                onAction: () => ref.invalidate(vouchersProvider),
              ),
              data: (page) => page.isEmpty
                  ? EmptyState(
                      title: strings.get('no_data'),
                      message: 'Create your first bill — it takes about ten seconds.',
                      icon: Icons.receipt_long_outlined,
                      actionLabel: strings.get('new_sale'),
                      onAction: () => context.goNamed(
                        Routes.invoiceForm,
                        queryParameters: {'type': type},
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: () async => ref.invalidate(vouchersProvider),
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                        itemCount: page.items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (_, index) =>
                            InvoiceRow(voucher: page.items[index], symbol: symbol),
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Horizontal selector used in place of a TabBar so it can live in an AppBar
/// bottom slot without a TabController.
class TabBarSelector extends StatelessWidget {
  const TabBarSelector({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
  });

  final String value;
  final Map<String, String> options;
  final ValueChanged<String> onChanged;

  /// Past this many, equal shares stop being readable — a seventh of a phone
  /// is not enough for "Delivery challan" — so the row scrolls instead.
  static const _maxEvenlySplit = 3;

  @override
  Widget build(BuildContext context) {
    final entries = options.entries.toList();
    final scrolls = entries.length > _maxEvenlySplit;

    final tabs = [
      for (final entry in entries)
        _Tab(
          label: entry.value,
          selected: value == entry.key,
          onTap: () => onChanged(entry.key),
          padded: scrolls,
        ),
    ];

    return SizedBox(
      height: 48,
      child: scrolls
          ? ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              children: tabs,
            )
          : Row(children: [for (final tab in tabs) Expanded(child: tab)]),
    );
  }
}

class _Tab extends StatelessWidget {
  const _Tab({
    required this.label,
    required this.selected,
    required this.onTap,
    required this.padded,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final bool padded;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Container(
        alignment: Alignment.center,
        padding: padded ? const EdgeInsets.symmetric(horizontal: 14) : null,
        decoration: BoxDecoration(
          border: Border(
            bottom: BorderSide(
              color: selected ? AppColors.primary : Colors.transparent,
              width: 2.5,
            ),
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected
                ? AppColors.primary
                : Theme.of(context).colorScheme.onSurfaceVariant,
            fontSize: 14,
          ),
        ),
      ),
    );
  }
}

class InvoiceRow extends StatelessWidget {
  const InvoiceRow({super.key, required this.voucher, required this.symbol});

  final Voucher voucher;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () =>
          context.goNamed(Routes.invoiceDetail, pathParameters: {'id': voucher.id}),
      child: Column(
        children: [
          Row(
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
                            voucher.partyName ?? 'Walk-in customer',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w700),
                          ),
                        ),
                        if (voucher.fromAi) ...[
                          const SizedBox(width: 6),
                          const Icon(Icons.auto_awesome,
                              size: 12, color: AppColors.primary),
                        ],
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${voucher.number} · ${Fmt.relative(voucher.voucherDate)}',
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
                  MoneyText(
                    voucher.total,
                    symbol: symbol,
                    decimals: false,
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  StatusChip(voucher.isOverdue ? 'overdue' : voucher.status, dense: true),
                ],
              ),
            ],
          ),
          if (!voucher.isPaid && voucher.status != 'cancelled') ...[
            const SizedBox(height: 8),
            Row(
              children: [
                Icon(
                  voucher.isOverdue ? Icons.schedule : Icons.hourglass_empty,
                  size: 13,
                  color: voucher.isOverdue ? AppColors.danger : theme.colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: 5),
                Text(
                  voucher.isOverdue
                      ? Fmt.overdueLabel(voucher.daysOverdue)
                      : 'Due ${Fmt.relative(voucher.dueDate)}',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: voucher.isOverdue
                        ? AppColors.danger
                        : theme.colorScheme.onSurfaceVariant,
                    fontWeight: voucher.isOverdue ? FontWeight.w700 : FontWeight.w500,
                  ),
                ),
                const Spacer(),
                Text(
                  'Due ${Fmt.money(voucher.balanceAmount, symbol: symbol, decimals: false)}',
                  style: theme.textTheme.labelSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: AppColors.danger,
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
