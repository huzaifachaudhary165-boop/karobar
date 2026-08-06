import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Cheques written and received.
///
/// A cheque is a promise, not money. The account balance only moves when the
/// bank settles it, which is why marking one cleared or bounced here is a real
/// action and not just a label change.
class ChequesScreen extends ConsumerWidget {
  const ChequesScreen({super.key});

  static const _filters = {
    null: 'In hand',
    'deposited': 'Deposited',
    'cleared': 'Cleared',
    'bounced': 'Bounced',
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(chequesProvider);
    final summary = ref.watch(chequeSummaryProvider);
    final filter = ref.watch(chequeFilterProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Cheques')),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(52),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: Row(
              children: [
                for (final entry in _filters.entries) ...[
                  ChoiceChip(
                    label: Text(context.t(entry.value)),
                    selected: filter == entry.key,
                    showCheckmark: false,
                    onSelected: (_) =>
                        ref.read(chequeFilterProvider.notifier).state = entry.key,
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(chequesProvider);
          ref.invalidate(chequeSummaryProvider);
        },
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load cheques'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(chequesProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('No cheques here'),
                  message: context.t(
                      'Record a payment with cheque as the mode and it shows up '
                      'here until the bank settles it.'),
                  icon: Icons.receipt_long_outlined,
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                  children: [
                    summary.maybeWhen(
                      data: (totals) => totals.isEmpty
                          ? const SizedBox.shrink()
                          : Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: _Summary(totals: totals, symbol: symbol),
                            ),
                      orElse: () => const SizedBox.shrink(),
                    ),
                    for (final cheque in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _ChequeCard(cheque: cheque, symbol: symbol),
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({required this.totals, required this.symbol});

  final ChequeSummary totals;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: StatTile(
                label: context.t('To deposit (${totals.toDepositCount})'),
                value: Fmt.money(totals.toDepositAmount, symbol: symbol, decimals: false),
                icon: Icons.call_received,
                accent: AppColors.success,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: StatTile(
                label: context.t('To clear (${totals.toClearCount})'),
                value: Fmt.money(totals.toClearAmount, symbol: symbol, decimals: false),
                icon: Icons.call_made,
                accent: AppColors.danger,
              ),
            ),
          ],
        ),
        if (totals.overdueCount > 0)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: AppCard(
              borderColor: AppColors.warning.withValues(alpha: 0.5),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              child: Row(
                children: [
                  const Icon(Icons.warning_amber_rounded,
                      size: 18, color: AppColors.warning),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      context.t('${totals.overdueCount} cheque(s) are past their date '
                          'and still unsettled.'),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _ChequeCard extends ConsumerWidget {
  const _ChequeCard({required this.cheque, required this.symbol});

  final Cheque cheque;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final tint = cheque.isIncoming ? AppColors.success : AppColors.danger;

    return AppCard(
      onTap: cheque.isSettled ? null : () => _act(context, ref),
      borderColor:
          cheque.isOverdue ? AppColors.warning.withValues(alpha: 0.5) : null,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
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
                  color: tint.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  cheque.isIncoming ? Icons.call_received : Icons.call_made,
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
                      cheque.partyName ?? context.t('Walk-in'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        if (cheque.referenceNumber != null &&
                            cheque.referenceNumber!.isNotEmpty)
                          '#${cheque.referenceNumber}',
                        if (cheque.chequeDate != null) Fmt.dateShort(cheque.chequeDate),
                      ].join('  ·  '),
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
                    Fmt.money(cheque.amount, symbol: symbol, decimals: false),
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w800, color: tint),
                  ),
                  const SizedBox(height: 3),
                  StatusChip(_chipStatus, label: Fmt.titleCase(cheque.status), dense: true),
                ],
              ),
            ],
          ),
          if (!cheque.isSettled) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                if (cheque.status == 'pending')
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => _set(context, ref, 'deposited'),
                      child: Text(context.t('Deposited')),
                    ),
                  ),
                if (cheque.status == 'pending') const SizedBox(width: 8),
                Expanded(
                  child: FilledButton(
                    onPressed: () => _set(context, ref, 'cleared'),
                    child: Text(context.t('Cleared')),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(foregroundColor: AppColors.danger),
                    onPressed: () => _bounce(context, ref),
                    child: Text(context.t('Bounced')),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  /// Maps a cheque state onto the app's shared status palette.
  String get _chipStatus => switch (cheque.status) {
        'cleared' => 'paid',
        'bounced' => 'overdue',
        'deposited' => 'partial',
        'cancelled' => 'cancelled',
        _ => 'pending',
      };

  Future<void> _act(BuildContext context, WidgetRef ref) async {
    // Tapping the card is the same as the buttons — a shopkeeper who taps the
    // row expects something, and a silent tap is what "dead button" means.
    await _set(context, ref, 'cleared');
  }

  Future<void> _set(BuildContext context, WidgetRef ref, String status) async {
    try {
      await ref.read(financeRepositoryProvider).setChequeStatus(cheque.id, status);
      ref.invalidate(chequesProvider);
      ref.invalidate(chequeSummaryProvider);
      ref.invalidate(bankAccountsProvider);
      if (context.mounted) {
        showSuccess(
          context,
          status == 'cleared'
              ? context.t('Cleared — the money is in the account now')
              : context.t('Updated'),
        );
      }
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  Future<void> _bounce(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Cheque bounced?')),
        content: Text(
          context.t('The amount will be taken back out of the account it was '
              'credited to, and the bill it settled goes back to unpaid.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialog, false),
            child: Text(context.t('Cancel')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialog, true),
            child: Text(context.t('Yes, it bounced')),
          ),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      await _set(context, ref, 'bounced');
    }
  }
}
