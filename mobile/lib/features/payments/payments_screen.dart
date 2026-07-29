import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Money in and money out, in one list. Payments are grouped by day because
/// that's how a shopkeeper reconciles the drawer at closing time.
class PaymentsScreen extends ConsumerWidget {
  const PaymentsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(paymentsProvider);
    final direction = ref.watch(paymentDirectionProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Payments')),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(52),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: Row(
              children: [
                for (final entry in {
                  null: 'All',
                  'in': 'Received',
                  'out': 'Paid out',
                }.entries) ...[
                  ChoiceChip(
                    label: Text(entry.value),
                    selected: direction == entry.key,
                    showCheckmark: false,
                    onSelected: (_) =>
                        ref.read(paymentDirectionProvider.notifier).state = entry.key,
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(paymentsProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: 'Could not load payments',
            message: error.toString(),
            isError: true,
            actionLabel: 'Retry',
            onAction: () => ref.invalidate(paymentsProvider),
          ),
          data: (page) => page.isEmpty
              ? const EmptyState(
                  title: 'No payments yet',
                  message: 'Payments you record against bills show up here.',
                  icon: Icons.payments_outlined,
                )
              : _GroupedList(payments: page.items, symbol: symbol),
        ),
      ),
    );
  }
}

class _GroupedList extends StatelessWidget {
  const _GroupedList({required this.payments, required this.symbol});

  final List<Payment> payments;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    // Group by calendar day, preserving the server's newest-first order.
    final groups = <String, List<Payment>>{};
    for (final payment in payments) {
      groups.putIfAbsent(Fmt.iso(payment.paymentDate), () => []).add(payment);
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        for (final entry in groups.entries) ...[
          _DayHeader(
            date: DateTime.parse(entry.key),
            payments: entry.value,
            symbol: symbol,
          ),
          for (final payment in entry.value)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _PaymentRow(payment: payment, symbol: symbol),
            ),
          const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _DayHeader extends StatelessWidget {
  const _DayHeader({required this.date, required this.payments, required this.symbol});

  final DateTime date;
  final List<Payment> payments;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final received = payments
        .where((p) => p.isIncoming)
        .fold<num>(0, (sum, p) => sum + p.amount);
    final paid = payments
        .where((p) => !p.isIncoming)
        .fold<num>(0, (sum, p) => sum + p.amount);

    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 10, 2, 8),
      child: Row(
        children: [
          Text(
            Fmt.relative(date),
            style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
          ),
          const Spacer(),
          if (received > 0)
            Text(
              '+${Fmt.money(received, symbol: symbol, decimals: false)}',
              style: theme.textTheme.labelMedium?.copyWith(
                color: AppColors.success,
                fontWeight: FontWeight.w700,
              ),
            ),
          if (received > 0 && paid > 0)
            Text('  ·  ', style: theme.textTheme.labelMedium),
          if (paid > 0)
            Text(
              '-${Fmt.money(paid, symbol: symbol, decimals: false)}',
              style: theme.textTheme.labelMedium?.copyWith(
                color: AppColors.danger,
                fontWeight: FontWeight.w700,
              ),
            ),
        ],
      ),
    );
  }
}

class _PaymentRow extends ConsumerWidget {
  const _PaymentRow({required this.payment, required this.symbol});

  final Payment payment;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final tint = payment.isIncoming ? AppColors.success : AppColors.danger;

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: payment.partyId == null
          ? null
          : () => context.goNamed(
                Routes.partyDetail,
                pathParameters: {'id': payment.partyId!},
              ),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: tint.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              payment.isIncoming ? Icons.call_received : Icons.call_made,
              size: 19,
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
                  payment.partyName ?? 'Walk-in',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Text(
                      payment.number,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(5),
                      ),
                      child: Text(
                        Fmt.titleCase(payment.mode),
                        style: theme.textTheme.labelSmall?.copyWith(fontSize: 10),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${payment.isIncoming ? '+' : '-'}'
                '${Fmt.money(payment.amount, symbol: symbol, decimals: false)}',
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w800, color: tint),
              ),
              if (payment.unallocatedAmount > 0)
                Text(
                  '${Fmt.money(payment.unallocatedAmount, symbol: symbol, decimals: false)} advance',
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
