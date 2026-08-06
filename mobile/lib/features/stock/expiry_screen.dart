import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Stock that has expired or is about to.
///
/// Expired first and loudest: that is money already lost and the shop needs to
/// stop it reaching a customer. What follows is still sellable, in the order it
/// has to move.
class ExpiryScreen extends ConsumerWidget {
  const ExpiryScreen({super.key});

  static const _windows = {7: '7 days', 30: '30 days', 90: '3 months', 365: '1 year'};

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(expiringBatchesProvider);
    final window = ref.watch(expiryWindowProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Expiring stock')),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(52),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: Row(
              children: [
                for (final entry in _windows.entries) ...[
                  ChoiceChip(
                    label: Text(context.t(entry.value)),
                    selected: window == entry.key,
                    showCheckmark: false,
                    onSelected: (_) =>
                        ref.read(expiryWindowProvider.notifier).state = entry.key,
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(expiringBatchesProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load batches'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(expiringBatchesProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('Nothing expiring'),
                  message: context.t(
                      'No batch expires within this window. Batches show up here '
                      'once you record expiry dates against your stock.'),
                  icon: Icons.event_available_outlined,
                )
              : _Body(rows: rows, symbol: symbol),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.rows, required this.symbol});

  final List<ExpiringBatch> rows;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final expired = rows.where((r) => r.isExpired).toList();
    final upcoming = rows.where((r) => !r.isExpired).toList();

    final expiredValue = expired.fold<num>(0, (sum, r) => sum + r.value);
    final upcomingValue = upcoming.fold<num>(0, (sum, r) => sum + r.value);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      children: [
        Row(
          children: [
            Expanded(
              child: StatTile(
                label: context.t('Already expired'),
                value: Fmt.money(expiredValue, symbol: symbol, decimals: false),
                icon: Icons.block,
                accent: AppColors.danger,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: StatTile(
                label: context.t('Expiring soon'),
                value: Fmt.money(upcomingValue, symbol: symbol, decimals: false),
                icon: Icons.schedule,
                accent: AppColors.warning,
              ),
            ),
          ],
        ),
        if (expired.isNotEmpty) ...[
          SectionHeader(context.t('Expired — do not sell (${expired.length})')),
          for (final row in expired)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _BatchRow(row: row, symbol: symbol),
            ),
        ],
        if (upcoming.isNotEmpty) ...[
          SectionHeader(context.t('Sell these first (${upcoming.length})')),
          for (final row in upcoming)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _BatchRow(row: row, symbol: symbol),
            ),
        ],
      ],
    );
  }
}

class _BatchRow extends StatelessWidget {
  const _BatchRow({required this.row, required this.symbol});

  final ExpiringBatch row;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final days = row.daysToExpiry;
    final tint = row.isExpired
        ? AppColors.danger
        : (days != null && days <= 7 ? AppColors.warning : AppColors.primary);

    return AppCard(
      borderColor: row.isExpired ? AppColors.danger.withValues(alpha: 0.4) : null,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: tint.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              row.isExpired ? Icons.dangerous_outlined : Icons.timelapse,
              size: 20,
              color: tint,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  row.itemName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  '${context.t('Batch')} ${row.batch.batchNumber}'
                  '  ·  ${Fmt.qty(row.batch.qty)} ${row.unitLabel}',
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
                _dueLabel(context, days),
                style: theme.textTheme.labelMedium
                    ?.copyWith(color: tint, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 2),
              Text(
                Fmt.money(row.value, symbol: symbol, decimals: false),
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ],
      ),
    );
  }

  String _dueLabel(BuildContext context, int? days) {
    if (days == null) return '—';
    if (days < 0) return context.t('${days.abs()}d ago');
    if (days == 0) return context.t('Today');
    return context.t('in ${days}d');
  }
}
