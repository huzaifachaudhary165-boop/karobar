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
import 'receive_payment_sheet.dart';

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
      // A screen about payments with no way to record one is a report, not a
      // feature. The empty state said "payments you record show up here" and
      // offered nothing to record with.
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => showReceivePaymentSheet(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.t('Record payment')),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(paymentsProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load payments'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(paymentsProvider),
          ),
          data: (page) => page.isEmpty
              ? EmptyState(
                  title: context.t('No payments yet'),
                  message: context.t(
                      'Record what a customer paid and it settles their oldest '
                      'bills for you.'),
                  icon: Icons.payments_outlined,
                  actionLabel: context.t('Record payment'),
                  onAction: () => showReceivePaymentSheet(context, ref),
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
          // A receipt keyed for the wrong amount had no way back at all — not
          // an edit, not even a delete. The shopkeeper's books said they had
          // been paid something they had not.
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert, size: 18),
            tooltip: context.t('More'),
            onSelected: (action) => _onAction(context, ref, action),
            itemBuilder: (_) => [
              PopupMenuItem(
                value: 'edit',
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.edit_outlined),
                  title: Text(context.t('Change amount')),
                ),
              ),
              PopupMenuItem(
                value: 'delete',
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.delete_outline, color: AppColors.danger),
                  title: Text(context.t('Delete'),
                      style: const TextStyle(color: AppColors.danger)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _onAction(BuildContext context, WidgetRef ref, String action) async {
    if (action == 'edit') {
      await _edit(context, ref);
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('Delete ${payment.number}?')),
        content: Text(
          context.t('The bills it paid go back to unpaid, and '
              '${payment.partyName ?? 'the customer'}\'s balance goes back to '
              'what it was.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(context.t('Keep it')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(context.t('Delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    try {
      await ref.read(paymentRepositoryProvider).delete(payment.id);
      if (!context.mounted) return;
      ref.invalidate(paymentsProvider);
      invalidateBusinessData(ref);
      showSuccess(context, '${payment.number} deleted.');
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  /// Only the amount.
  ///
  /// Which bills it settled, and in what order, is the server's arithmetic —
  /// re-doing that from a list on a phone is how a payment ends up allocated
  /// twice. Changing the figure is the correction people actually need, and
  /// the server re-spreads it across the same bills.
  Future<void> _edit(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController(text: Fmt.qty(payment.amount));

    final amount = await showDialog<num>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('Change ${payment.number}')),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(
            labelText: context.t('Amount'),
            prefixText: symbol,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: Text(context.t('Cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(
              dialogContext,
              num.tryParse(controller.text.trim()),
            ),
            child: Text(context.t('Save')),
          ),
        ],
      ),
    );
    controller.dispose();

    if (amount == null || amount <= 0 || !context.mounted) return;
    if (amount == payment.amount) return;

    try {
      await ref
          .read(paymentRepositoryProvider)
          .update(payment.id, {'amount': amount});
      if (!context.mounted) return;
      ref.invalidate(paymentsProvider);
      invalidateBusinessData(ref);
      showSuccess(context, '${payment.number} updated.');
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}
