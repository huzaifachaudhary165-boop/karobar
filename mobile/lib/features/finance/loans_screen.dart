import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'loan_detail_screen.dart';
import 'loan_form_sheet.dart';

/// What the shop has borrowed and what is still owed.
class LoansScreen extends ConsumerWidget {
  const LoansScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(loansProvider);
    final summary = ref.watch(loanSummaryProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Loans'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => showLoanFormSheet(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.t('Add a loan')),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(loansProvider);
          ref.invalidate(loanSummaryProvider);
        },
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load loans'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(loansProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('No loans recorded'),
                  message: context.t(
                      'Add anything you have borrowed — a bank loan, or money from '
                      'family with no interest at all. The app works out the '
                      'instalments and keeps the balance.'),
                  icon: Icons.request_quote_outlined,
                  actionLabel: context.t('Add a loan'),
                  onAction: () => showLoanFormSheet(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
                  children: [
                    summary.maybeWhen(
                      data: (totals) => _Summary(totals: totals, symbol: symbol),
                      orElse: () => const SizedBox.shrink(),
                    ),
                    const SizedBox(height: 6),
                    for (final loan in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _LoanCard(loan: loan, symbol: symbol),
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

  final LoanSummary totals;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: StatTile(
            label: context.t('Still owed'),
            value: Fmt.money(totals.totalOutstanding, symbol: symbol, decimals: false),
            icon: Icons.account_balance_wallet_outlined,
            accent: AppColors.danger,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: StatTile(
            label: context.t('Every month'),
            value: Fmt.money(totals.monthlyCommitment, symbol: symbol, decimals: false),
            icon: Icons.event_repeat,
            accent: AppColors.warning,
          ),
        ),
      ],
    );
  }
}

class _LoanCard extends StatelessWidget {
  const _LoanCard({required this.loan, required this.symbol});

  final Loan loan;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dueSoon = loan.nextDueDate != null &&
        loan.nextDueDate!.difference(DateTime.now()).inDays <= 7;

    return AppCard(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => LoanDetailScreen(loanId: loan.id)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
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
                      loan.lenderName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        Fmt.titleCase(loan.loanType),
                        if (loan.isInterestFree)
                          context.t('interest-free')
                        else
                          '${loan.interestRate}% ${loan.interestType}',
                      ].join('  ·  '),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
              StatusChip(loan.isClosed ? 'paid' : 'pending',
                  label: loan.isClosed ? 'Settled' : 'Active', dense: true),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: loan.progress,
              minHeight: 6,
              backgroundColor: theme.colorScheme.surfaceContainerHighest,
              valueColor: AlwaysStoppedAnimation(
                loan.isClosed ? AppColors.success : AppColors.primary,
              ),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _Figure(
                  label: context.t('Still owed'),
                  value: Fmt.money(loan.outstandingPrincipal,
                      symbol: symbol, decimals: false),
                ),
              ),
              if (!loan.isClosed && loan.emiAmount > 0)
                Expanded(
                  child: _Figure(
                    label: context.t('Instalment'),
                    value: Fmt.money(loan.emiAmount, symbol: symbol, decimals: false),
                  ),
                ),
              if (loan.tenureMonths > 0)
                Expanded(
                  child: _Figure(
                    label: context.t('Paid'),
                    value: '${loan.instalmentsPaid}/${loan.tenureMonths}',
                  ),
                ),
            ],
          ),
          if (!loan.isClosed && loan.nextDueDate != null) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                Icon(
                  Icons.event_outlined,
                  size: 14,
                  color: dueSoon ? AppColors.warning : theme.colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: 6),
                Text(
                  context.t('Next due ${Fmt.dateShort(loan.nextDueDate)}'),
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: dueSoon
                        ? AppColors.warning
                        : theme.colorScheme.onSurfaceVariant,
                    fontWeight: dueSoon ? FontWeight.w700 : null,
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
