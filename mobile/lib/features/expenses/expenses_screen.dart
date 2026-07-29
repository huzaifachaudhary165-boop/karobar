import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

class ExpensesScreen extends ConsumerWidget {
  const ExpensesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(expensesProvider);
    final categories = ref.watch(expenseCategoriesProvider);
    final symbol = ref.watch(sessionProvider).symbol;
    final strings = context.s;

    return Scaffold(
      appBar: AppBar(
        title: Text(strings.get('expenses')),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            tooltip: strings.get('add_expense'),
            onPressed: () => context.goNamed(Routes.expenseForm),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(expensesProvider);
          ref.invalidate(expenseCategoriesProvider);
        },
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: 'Could not load expenses',
            message: error.toString(),
            isError: true,
            actionLabel: strings.get('retry'),
            onAction: () => ref.invalidate(expensesProvider),
          ),
          data: (page) => page.isEmpty
              ? EmptyState(
                  title: strings.get('no_data'),
                  message: 'Record rent, salaries, transport and everything else '
                      'so your profit figure is real.',
                  icon: Icons.receipt_outlined,
                  actionLabel: strings.get('add_expense'),
                  onAction: () => context.goNamed(Routes.expenseForm),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                  children: [
                    categories.maybeWhen(
                      data: (rows) => _CategorySummary(categories: rows, symbol: symbol),
                      orElse: () => const SizedBox.shrink(),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'All expenses',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    for (final expense in page.items)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _ExpenseRow(expense: expense, symbol: symbol),
                      ),
                  ],
                ),
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'expense-add',
        onPressed: () => context.goNamed(Routes.expenseForm),
        icon: const Icon(Icons.add),
        label: Text(strings.get('add_expense')),
      ),
    );
  }
}

class _CategorySummary extends StatelessWidget {
  const _CategorySummary({required this.categories, required this.symbol});

  final List<ExpenseCategory> categories;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final spending = categories.where((c) => c.spentThisMonth > 0).toList()
      ..sort((a, b) => b.spentThisMonth.compareTo(a.spentThisMonth));
    if (spending.isEmpty) return const SizedBox.shrink();

    final total = spending.fold<num>(0, (sum, c) => sum + c.spentThisMonth);
    final theme = Theme.of(context);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text('This month', style: theme.textTheme.titleSmall),
              const Spacer(),
              MoneyText(
                total,
                symbol: symbol,
                decimals: false,
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
              ),
            ],
          ),
          const SizedBox(height: 14),
          for (final category in spending.take(5)) ...[
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          category.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodySmall,
                        ),
                      ),
                      Text(
                        Fmt.money(category.spentThisMonth, symbol: symbol, decimals: false),
                        style: theme.textTheme.labelMedium
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ],
                  ),
                  const SizedBox(height: 5),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: total == 0 ? 0 : category.spentThisMonth / total,
                      minHeight: 5,
                      backgroundColor: theme.colorScheme.surfaceContainerHighest,
                      valueColor: const AlwaysStoppedAnimation(AppColors.warning),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ExpenseRow extends ConsumerWidget {
  const _ExpenseRow({required this.expense, required this.symbol});

  final Expense expense;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final fromScan = expense.source == 'ocr' || expense.source == 'ai';

    return Dismissible(
      key: ValueKey(expense.id),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        decoration: BoxDecoration(
          color: AppColors.danger,
          borderRadius: BorderRadius.circular(14),
        ),
        child: const Icon(Icons.delete_outline, color: Colors.white),
      ),
      confirmDismiss: (_) async {
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(context.t('Delete this expense?')),
            content: Text('${expense.title} — '
                '${Fmt.money(expense.total, symbol: symbol, decimals: false)}'),
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
        if (confirmed != true) return false;

        try {
          await ref.read(expenseRepositoryProvider).delete(expense.id);
          if (context.mounted) {
            ref.invalidate(expensesProvider);
            invalidateBusinessData(ref);
            showSuccess(context, 'Expense deleted.');
          }
          return true;
        } catch (error) {
          if (context.mounted) showError(context, error);
          return false;
        }
      },
      child: AppCard(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: AppColors.softTint(AppColors.warning, Theme.of(context).brightness),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.receipt_outlined,
                  size: 19, color: AppColors.warning),
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
                          expense.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.titleSmall
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ),
                      if (fromScan) ...[
                        const SizedBox(width: 6),
                        const Icon(Icons.auto_awesome, size: 12, color: AppColors.primary),
                      ],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    [
                      expense.categoryName ?? 'Uncategorised',
                      Fmt.relative(expense.expenseDate),
                    ].join(' · '),
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
            MoneyText(
              expense.total,
              symbol: symbol,
              decimals: false,
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w800,
                color: AppColors.danger,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
