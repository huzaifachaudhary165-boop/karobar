import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'recurring_form_sheet.dart';

/// Bills that repeat, and what is owed on them right now.
class RecurringScreen extends ConsumerWidget {
  const RecurringScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(recurringBillsProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Repeating bills')),
        actions: [
          IconButton(
            icon: const Icon(Icons.play_circle_outline),
            tooltip: context.t('Raise everything due'),
            onPressed: () => _runDue(context, ref),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => showRecurringFormSheet(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.t('New')),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(recurringBillsProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load repeating bills'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(recurringBillsProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('Nothing repeats yet'),
                  message: context.t(
                      'Rent, a subscription, a standing monthly order — set it '
                      'up once and the bill raises itself.'),
                  icon: Icons.event_repeat_outlined,
                  actionLabel: context.t('Set one up'),
                  onAction: () => showRecurringFormSheet(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 90),
                  children: [
                    for (final bill in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _BillCard(bill: bill, symbol: symbol),
                      ),
                  ],
                ),
        ),
      ),
    );
  }

  Future<void> _runDue(BuildContext context, WidgetRef ref) async {
    try {
      final run = await ref.read(recurringRepositoryProvider).runDue();
      ref.invalidate(recurringBillsProvider);
      invalidateBusinessData(ref);
      if (!context.mounted) return;

      if (run.isQuiet) {
        showSuccess(context, context.t('Nothing is due today'));
        return;
      }
      await showDialog<void>(
        context: context,
        builder: (_) => _RunReport(run: run, symbol: ref.read(sessionProvider).symbol),
      );
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _BillCard extends ConsumerWidget {
  const _BillCard({required this.bill, required this.symbol});

  final RecurringBill bill;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final dormant = !bill.isActive || bill.isFinished;

    return AppCard(
      onTap: () => _menu(context, ref),
      borderColor: bill.isDue ? AppColors.warning.withValues(alpha: 0.5) : null,
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
                      bill.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: dormant ? theme.colorScheme.onSurfaceVariant : null,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        bill.scheduleLabel,
                        if (bill.partyName != null) bill.partyName!,
                      ].join('  ·  '),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
              StatusChip(
                bill.isFinished
                    ? 'paid'
                    : !bill.isActive
                        ? 'cancelled'
                        : bill.isDue
                            ? 'overdue'
                            : 'pending',
                label: bill.isFinished
                    ? 'Finished'
                    : !bill.isActive
                        ? 'Paused'
                        : bill.isDue
                            ? 'Due now'
                            : 'Scheduled',
                dense: true,
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _Figure(
                  label: bill.isDue ? context.t('Was due') : context.t('Next'),
                  value: Fmt.dateShort(bill.nextRunOn),
                  tint: bill.isDue ? AppColors.warning : null,
                ),
              ),
              Expanded(
                child: _Figure(
                  label: context.t('Each time'),
                  value: Fmt.money(bill.estimatedTotal, symbol: symbol, decimals: false),
                ),
              ),
              Expanded(
                child: _Figure(
                  label: context.t('Raised'),
                  value: bill.maxOccurrences == null
                      ? '${bill.occurrences}'
                      : '${bill.occurrences}/${bill.maxOccurrences}',
                ),
              ),
            ],
          ),

          // A schedule that wants checking first says so, because otherwise a
          // shopkeeper wonders why the bill has not gone out.
          if (!bill.autoCreate && bill.isActive)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Row(
                children: [
                  const Icon(Icons.visibility_outlined, size: 14),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      context.t('Reminds you instead of raising it'),
                      style: theme.textTheme.labelSmall,
                    ),
                  ),
                ],
              ),
            ),

          if (bill.lastError != null)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, size: 14, color: AppColors.danger),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      bill.lastError!,
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: AppColors.danger),
                    ),
                  ),
                ],
              ),
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
            if (!bill.isFinished)
              ListTile(
                leading: const Icon(Icons.receipt_long_outlined),
                title: Text(context.t('Raise this bill now')),
                subtitle: Text(context.t('Even if it is not due yet')),
                onTap: () => Navigator.pop(sheet, 'run'),
              ),
            ListTile(
              leading: Icon(bill.isActive ? Icons.pause : Icons.play_arrow),
              title: Text(bill.isActive ? context.t('Pause') : context.t('Resume')),
              onTap: () => Navigator.pop(sheet, 'toggle'),
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: AppColors.danger),
              title: Text(
                context.t('Stop and remove'),
                style: const TextStyle(color: AppColors.danger),
              ),
              subtitle: Text(context.t('Bills already raised are untouched')),
              onTap: () => Navigator.pop(sheet, 'delete'),
            ),
          ],
        ),
      ),
    );
    if (choice == null || !context.mounted) return;

    final repository = ref.read(recurringRepositoryProvider);
    try {
      switch (choice) {
        case 'run':
          await repository.runOne(bill.id);
          invalidateBusinessData(ref);
          if (context.mounted) showSuccess(context, context.t('Bill raised'));
        case 'toggle':
          await repository.update(bill.id, {'is_active': !bill.isActive});
        case 'delete':
          await repository.delete(bill.id);
      }
      ref.invalidate(recurringBillsProvider);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Figure extends StatelessWidget {
  const _Figure({required this.label, required this.value, this.tint});

  final String label;
  final String value;
  final Color? tint;

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
            color: tint,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }
}

/// What the run actually did.
///
/// Shown rather than a toast: bills went out in the shop's name and the
/// shopkeeper is entitled to see which, for how much, before carrying on.
class _RunReport extends StatelessWidget {
  const _RunReport({required this.run, required this.symbol});

  final RecurringRun run;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AlertDialog(
      title: Text(
        run.created.isEmpty
            ? context.t('Nothing raised')
            : context.t('${run.created.length} bill(s) raised'),
      ),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final bill in run.created)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${bill.number}  ·  ${bill.name}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                    Text(
                      Fmt.money(bill.total, symbol: symbol, decimals: false),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
              ),
            if (run.created.isNotEmpty) ...[
              const Divider(),
              Row(
                children: [
                  Expanded(
                    child: Text(context.t('Total'),
                        style: theme.textTheme.bodyMedium),
                  ),
                  Text(
                    Fmt.money(run.totalRaised, symbol: symbol, decimals: false),
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ],
              ),
            ],
            for (final reminder in run.reminders)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  context.t('${reminder['name']} is due — '
                      'it is set to remind you, not raise itself.'),
                  style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
                ),
              ),
            for (final problem in run.problems)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  '${problem['name']}: ${problem['reason']}',
                  style: theme.textTheme.bodySmall?.copyWith(color: AppColors.danger),
                ),
              ),
          ],
        ),
      ),
      actions: [
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: Text(context.t('Done')),
        ),
      ],
    );
  }
}
