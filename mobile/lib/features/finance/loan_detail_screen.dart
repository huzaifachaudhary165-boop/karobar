import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// One loan: what is owed, what has been paid, and the plan ahead.
class LoanDetailScreen extends ConsumerWidget {
  const LoanDetailScreen({super.key, required this.loanId});

  final String loanId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(loanProvider(loanId));
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Loan')),
        actions: [
          async.maybeWhen(
            data: (loan) => IconButton(
              icon: const Icon(Icons.delete_outline),
              onPressed: () => _delete(context, ref, loan),
            ),
            orElse: () => const SizedBox.shrink(),
          ),
        ],
      ),
      floatingActionButton: async.maybeWhen(
        data: (loan) => loan.isClosed
            ? null
            : FloatingActionButton.extended(
                onPressed: () => _repay(context, ref, loan),
                icon: const Icon(Icons.payments_outlined),
                label: Text(context.t('Record repayment')),
              ),
        orElse: () => null,
      ),
      body: async.when(
        loading: () => const ListSkeleton(),
        error: (error, _) => EmptyState(
          title: context.t('Could not load this loan'),
          message: error.toString(),
          isError: true,
          actionLabel: context.t('Retry'),
          onAction: () => ref.invalidate(loanProvider(loanId)),
        ),
        data: (loan) => RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(loanProvider(loanId));
            ref.invalidate(loanPaymentsProvider(loanId));
            ref.invalidate(loanScheduleProvider(loanId));
          },
          child: _Body(loan: loan, symbol: symbol),
        ),
      ),
    );
  }

  Future<void> _repay(BuildContext context, WidgetRef ref, Loan loan) async {
    final paid = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _RepaymentSheet(loan: loan),
    );
    if (paid == true) {
      ref.invalidate(loanProvider(loan.id));
      ref.invalidate(loanPaymentsProvider(loan.id));
      ref.invalidate(loansProvider);
      ref.invalidate(loanSummaryProvider);
      ref.invalidate(bankAccountsProvider);
    }
  }

  Future<void> _delete(BuildContext context, WidgetRef ref, Loan loan) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Delete this loan?')),
        content: Text(
          context.t('Any repayments recorded against it have to be removed first.'),
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
      await ref.read(financeRepositoryProvider).deleteLoan(loan.id);
      ref.invalidate(loansProvider);
      ref.invalidate(loanSummaryProvider);
      if (context.mounted) Navigator.pop(context);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.loan, required this.symbol});

  final Loan loan;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final payments = ref.watch(loanPaymentsProvider(loan.id));
    final schedule = ref.watch(loanScheduleProvider(loan.id));

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                loan.lenderName,
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 2),
              Text(
                [
                  Fmt.titleCase(loan.loanType),
                  if (loan.isInterestFree)
                    context.t('interest-free')
                  else
                    '${loan.interestRate}% ${loan.interestType}',
                  if (loan.tenureMonths > 0)
                    '${loan.tenureMonths} ${context.t('months')}',
                ].join('  ·  '),
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 14),
              ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(
                  value: loan.progress,
                  minHeight: 8,
                  backgroundColor: theme.colorScheme.surfaceContainerHighest,
                  valueColor: AlwaysStoppedAnimation(
                    loan.isClosed ? AppColors.success : AppColors.primary,
                  ),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                context.t('${(loan.progress * 100).round()}% of the debt repaid'),
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: StatTile(
                label: context.t('Still owed'),
                value: Fmt.money(loan.outstandingPrincipal, symbol: symbol, decimals: false),
                icon: Icons.account_balance_wallet_outlined,
                accent: loan.isClosed ? AppColors.success : AppColors.danger,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: StatTile(
                label: context.t('Interest paid'),
                value: Fmt.money(loan.interestPaid, symbol: symbol, decimals: false),
                icon: Icons.percent,
                accent: AppColors.warning,
              ),
            ),
          ],
        ),

        // The interest half is the only part that is an expense. Saying so here
        // is cheaper than a shopkeeper's accountant finding it in March.
        if (loan.interestPaid > 0)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: AppCard(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              child: Row(
                children: [
                  const Icon(Icons.info_outline, size: 18),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      context.t('Only the interest counts as a business expense. '
                          'The rest repays the debt.'),
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
          ),

        payments.maybeWhen(
          data: (rows) => rows.isEmpty
              ? const SizedBox.shrink()
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SectionHeader(context.t('Repayments made (${rows.length})')),
                    for (final row in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _PaymentRow(
                          payment: row,
                          loanId: loan.id,
                          symbol: symbol,
                        ),
                      ),
                  ],
                ),
          orElse: () => const SizedBox.shrink(),
        ),

        schedule.maybeWhen(
          data: (rows) {
            final ahead = rows.skip(loan.instalmentsPaid).take(6).toList();
            if (ahead.isEmpty) return const SizedBox.shrink();
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SectionHeader(context.t('Coming up')),
                for (final row in ahead)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _ScheduleRow(instalment: row, symbol: symbol),
                  ),
              ],
            );
          },
          orElse: () => const SizedBox.shrink(),
        ),
      ],
    );
  }
}

class _PaymentRow extends ConsumerWidget {
  const _PaymentRow({
    required this.payment,
    required this.loanId,
    required this.symbol,
  });

  final LoanPayment payment;
  final String loanId;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () => _undo(context, ref),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  payment.instalmentNumber == null
                      ? Fmt.date(payment.paymentDate)
                      : '${context.t('Instalment')} ${payment.instalmentNumber}'
                          '  ·  ${Fmt.dateShort(payment.paymentDate)}',
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  '${context.t('Debt')} '
                  '${Fmt.money(payment.principalComponent, symbol: symbol, decimals: false)}'
                  '  ·  ${context.t('Interest')} '
                  '${Fmt.money(payment.interestComponent, symbol: symbol, decimals: false)}',
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
                Fmt.money(payment.amount, symbol: symbol, decimals: false),
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              Text(
                '${context.t('left')} '
                '${Fmt.money(payment.balanceAfter, symbol: symbol, decimals: false)}',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _undo(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Remove this repayment?')),
        content: Text(
          context.t('The amount goes back onto what you owe, and back into the '
              'account it was paid from.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialog, false),
            child: Text(context.t('Cancel')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialog, true),
            child: Text(context.t('Remove')),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    try {
      await ref.read(financeRepositoryProvider).deleteLoanPayment(loanId, payment.id);
      ref.invalidate(loanProvider(loanId));
      ref.invalidate(loanPaymentsProvider(loanId));
      ref.invalidate(loansProvider);
      ref.invalidate(loanSummaryProvider);
      ref.invalidate(bankAccountsProvider);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _ScheduleRow extends StatelessWidget {
  const _ScheduleRow({required this.instalment, required this.symbol});

  final LoanInstalment instalment;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
      color: theme.colorScheme.surfaceContainerLowest,
      child: Row(
        children: [
          SizedBox(
            width: 28,
            child: Text(
              '${instalment.number}',
              style: theme.textTheme.labelMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  Fmt.dateShort(instalment.dueDate),
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
                Text(
                  '${context.t('Debt')} '
                  '${Fmt.money(instalment.principal, symbol: symbol, decimals: false)}'
                  '  ·  ${context.t('Interest')} '
                  '${Fmt.money(instalment.interest, symbol: symbol, decimals: false)}',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          Text(
            Fmt.money(instalment.amount, symbol: symbol, decimals: false),
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

class _RepaymentSheet extends ConsumerStatefulWidget {
  const _RepaymentSheet({required this.loan});

  final Loan loan;

  @override
  ConsumerState<_RepaymentSheet> createState() => _RepaymentSheetState();
}

class _RepaymentSheetState extends ConsumerState<_RepaymentSheet> {
  late final _amount = TextEditingController(
    text: widget.loan.emiAmount > 0 ? widget.loan.emiAmount.toString() : '',
  );
  final _reference = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  String? _accountId;
  bool _saving = false;

  @override
  void dispose() {
    _amount.dispose();
    _reference.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;
    final accounts = ref.watch(bankAccountsProvider).valueOrNull ?? const <BankAccount>[];

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
              context.t('Record repayment'),
              style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            Text(
              context.t('${Fmt.money(widget.loan.outstandingPrincipal, symbol: symbol)} '
                  'still owed to ${widget.loan.lenderName}'),
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _amount,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: context.t('Amount paid')),
              validator: (value) {
                final amount = num.tryParse((value ?? '').trim());
                if (amount == null || amount <= 0) return context.t('Enter the amount');
                return null;
              },
            ),
            const SizedBox(height: 12),
            if (accounts.isNotEmpty)
              DropdownButtonFormField<String>(
                initialValue: _accountId,
                decoration: InputDecoration(labelText: context.t('Paid from')),
                items: [
                  for (final account in accounts)
                    DropdownMenuItem(value: account.id, child: Text(account.name)),
                ],
                onChanged: (value) => setState(() => _accountId = value),
              ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _reference,
              decoration: InputDecoration(
                labelText: context.t('Reference'),
                hintText: context.t('Optional'),
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
    );
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);
    try {
      await ref.read(financeRepositoryProvider).repayLoan(
            widget.loan.id,
            amount: num.parse(_amount.text.trim()),
            accountId: _accountId,
            referenceNumber: _reference.text.trim(),
          );
      if (mounted) {
        Navigator.pop(context, true);
        showSuccess(context, context.t('Repayment recorded'));
      }
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}
