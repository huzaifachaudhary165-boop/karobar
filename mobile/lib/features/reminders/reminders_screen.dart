import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/chase.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Everything still to be done, and who it is about.
///
/// The list a shopkeeper wanted so that "kis kis ne dena hai" is a screen
/// rather than something held in their head. Notifications already tell them
/// what the *app* worked out — an overdue bill, low stock — but not the things
/// they decided themselves, which are usually the ones that matter and the
/// ones that get forgotten.
class RemindersScreen extends ConsumerWidget {
  const RemindersScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Two lists, because a shopkeeper means two different things by "what am I
    // owed". One is what they wrote down; the other is what the books already
    // know and nobody had to type.
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(context.t('Reminders')),
          bottom: TabBar(
            tabs: [
              Tab(text: context.t('To do')),
              Tab(text: context.t('Who owes me')),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            _ToDoTab(),
            _OwingTab(),
          ],
        ),
        floatingActionButton: Consumer(
          builder: (context, ref, _) => FloatingActionButton.extended(
            onPressed: () => showReminderSheet(context, ref),
            icon: const Icon(Icons.add_alarm),
            label: Text(context.t('Remind me')),
          ),
        ),
      ),
    );
  }
}

/// Everybody whose balance says they still owe, straight from the books.
///
/// Nobody types this list — it is already true. What was missing was somewhere
/// to see it as a list of *people to contact* rather than as balances, with the
/// three ways a shop actually gets hold of somebody on each row.
class _OwingTab extends ConsumerWidget {
  const _OwingTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(owingPartiesProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(owingPartiesProvider),
      child: async.when(
        loading: () => const ListSkeleton(),
        error: (error, _) => EmptyState(
          title: context.t('Could not load'),
          message: error.toString(),
          isError: true,
          actionLabel: context.t('Retry'),
          onAction: () => ref.invalidate(owingPartiesProvider),
        ),
        data: (rows) {
          if (rows.isEmpty) {
            return EmptyState(
              title: context.t('Nobody owes you anything'),
              message: context.t('Every customer is settled up. This list '
                  'fills itself from your bills — nothing to type.'),
              icon: Icons.verified_outlined,
            );
          }

          final total = rows.fold<num>(0, (sum, p) => sum + p.balance);

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
            children: [
              AppCard(
                color: AppColors.danger.withValues(alpha: 0.07),
                borderColor: AppColors.danger.withValues(alpha: 0.3),
                child: Row(
                  children: [
                    const Icon(Icons.account_balance_wallet_outlined,
                        color: AppColors.danger),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            context.t('${rows.length} people owe you'),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                          Text(
                            Fmt.money(total, symbol: symbol, decimals: false),
                            style: Theme.of(context)
                                .textTheme
                                .titleLarge
                                ?.copyWith(
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.danger,
                                ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              for (final party in rows) ...[
                _OwingCard(party: party, symbol: symbol),
                const SizedBox(height: 8),
              ],
            ],
          );
        },
      ),
    );
  }
}

/// One person who owes, and the three ways to reach them.
class _OwingCard extends ConsumerWidget {
  const _OwingCard({required this.party, required this.symbol});

  final Party party;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return AppCard(
      padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
      onTap: () => context.goNamed(
        Routes.partyDetail,
        pathParameters: {'id': party.id},
      ),
      child: Row(
        children: [
          NameAvatar(party.name, size: 40),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  party.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                Text(
                  Fmt.money(party.balance, symbol: symbol, decimals: false),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: AppColors.danger,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (!Chase.canCall(party) && !Chase.canEmail(party))
                  Text(
                    // Said rather than left as an empty row, because the
                    // shopkeeper is looking for a way to reach them and there
                    // is one — it just has to be saved first.
                    context.t('No phone or email saved'),
                    style: theme.textTheme.bodySmall,
                  ),
              ],
            ),
          ),
          ChaseButtons(party: party, symbol: symbol, dense: true),
        ],
      ),
    );
  }
}

/// The reminders somebody wrote down themselves.
class _ToDoTab extends ConsumerWidget {
  const _ToDoTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(remindersProvider);
    final summary = ref.watch(reminderSummaryProvider).valueOrNull;
    final symbol = ref.watch(sessionProvider).symbol;

    return RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(remindersProvider);
          ref.invalidate(reminderSummaryProvider);
        },
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load your reminders'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(remindersProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('Nothing to remember'),
                  message: context.t('Put anything here you do not want to '
                      'forget — money to collect, a supplier to call, stock to '
                      'order. You will be told when it is time.'),
                  icon: Icons.alarm_off,
                  actionLabel: context.t('Add the first one'),
                  onAction: () => showReminderSheet(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
                  children: [
                    if (summary != null && summary.amountOutstanding > 0)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: _OutstandingCard(
                          summary: summary,
                          symbol: symbol,
                        ),
                      ),
                    for (final reminder in rows) ...[
                      _ReminderCard(reminder: reminder, symbol: symbol),
                      const SizedBox(height: 8),
                    ],
                  ],
                ),
      ),
    );
  }
}

/// What the outstanding reminders come to, added up.
///
/// Only for the ones about money. A shopkeeper who has written down six
/// promises wants the total without doing it in their head.
class _OutstandingCard extends StatelessWidget {
  const _OutstandingCard({required this.summary, required this.symbol});

  final ReminderSummary summary;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppCard(
      color: AppColors.primary.withValues(alpha: 0.07),
      borderColor: AppColors.primary.withValues(alpha: 0.3),
      child: Row(
        children: [
          const Icon(Icons.savings_outlined, color: AppColors.primary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(context.t('Written down to collect'),
                    style: theme.textTheme.bodySmall),
                Text(
                  Fmt.money(summary.amountOutstanding,
                      symbol: symbol, decimals: false),
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    color: AppColors.primary,
                  ),
                ),
              ],
            ),
          ),
          if (summary.dueNow > 0)
            StatusChip('overdue',
                label: context.t('${summary.dueNow} due now'), dense: true),
        ],
      ),
    );
  }
}

class _ReminderCard extends ConsumerWidget {
  const _ReminderCard({required this.reminder, required this.symbol});

  final Reminder reminder;
  final String symbol;

  Future<void> _act(BuildContext context, WidgetRef ref, String action) async {
    final repository = ref.read(reminderRepositoryProvider);
    try {
      switch (action) {
        case 'done':
          await repository.setDone(reminder.id);
          if (context.mounted) showSuccess(context, 'Done.');
        case 'snooze':
          await repository.snooze(reminder.id, days: 1);
          if (context.mounted) showSuccess(context, 'Tomorrow, then.');
        case 'week':
          await repository.snooze(reminder.id, days: 7);
          if (context.mounted) showSuccess(context, 'Next week, then.');
        case 'delete':
          await repository.delete(reminder.id);
          if (context.mounted) showSuccess(context, 'Removed.');
      }
      ref.invalidate(remindersProvider);
      ref.invalidate(reminderSummaryProvider);
      // The bell reads from the server's own list of what is due.
      ref.invalidate(unreadCountProvider);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final late = reminder.isDue;
    final days = reminder.daysLate;

    return AppCard(
      borderColor: late ? AppColors.danger.withValues(alpha: 0.35) : null,
      padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Ticking off is the commonest thing done here, so it is a tap on
          // the row rather than something inside a menu.
          IconButton(
            icon: const Icon(Icons.check_circle_outline),
            color: AppColors.success,
            tooltip: context.t('Done'),
            onPressed: () => _act(context, ref, 'done'),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  reminder.title,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Wrap(
                  spacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (reminder.partyName != null)
                      Text(reminder.partyName!, style: theme.textTheme.bodySmall),
                    if (reminder.amount != null && reminder.amount! > 0)
                      Text(
                        Fmt.money(reminder.amount!, symbol: symbol, decimals: false),
                        style: theme.textTheme.bodySmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: AppColors.primary,
                        ),
                      ),
                    Text(
                      // Said the way somebody would say it out loud, rather
                      // than as a date they then have to work out.
                      late
                          ? (days <= 0
                              ? context.t('today')
                              : context.t('$days day${days == 1 ? '' : 's'} late'))
                          : Fmt.date(reminder.dueAt),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: late ? AppColors.danger : null,
                        fontWeight: late ? FontWeight.w700 : null,
                      ),
                    ),
                  ],
                ),
                if (reminder.note != null && reminder.note!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(reminder.note!, style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert, size: 18),
            onSelected: (action) => _act(context, ref, action),
            itemBuilder: (_) => [
              PopupMenuItem(
                value: 'snooze',
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.snooze),
                  title: Text(context.t('Tomorrow')),
                ),
              ),
              PopupMenuItem(
                value: 'week',
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.next_week_outlined),
                  title: Text(context.t('Next week')),
                ),
              ),
              PopupMenuItem(
                value: 'delete',
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.delete_outline, color: AppColors.danger),
                  title: Text(context.t('Remove'),
                      style: const TextStyle(color: AppColors.danger)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Writes one down.
///
/// [party] pre-fills who it is about, so "remind me about this customer" from
/// their own screen does not mean typing their name again.
Future<void> showReminderSheet(
  BuildContext context,
  WidgetRef ref, {
  Party? party,
  num? amount,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _ReminderSheet(party: party, amount: amount),
  );
}

class _ReminderSheet extends ConsumerStatefulWidget {
  const _ReminderSheet({this.party, this.amount});

  final Party? party;
  final num? amount;

  @override
  ConsumerState<_ReminderSheet> createState() => _ReminderSheetState();
}

class _ReminderSheetState extends ConsumerState<_ReminderSheet> {
  final _title = TextEditingController();
  final _amount = TextEditingController();

  /// Days from now. Tomorrow is the honest default — a reminder for right now
  /// is a thing you are already doing.
  int _inDays = 1;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (widget.party != null) {
      _title.text = 'Follow up with ${widget.party!.name}';
    }
    if (widget.amount != null && widget.amount! > 0) {
      _amount.text = trimZeros(widget.amount!);
    }
  }

  @override
  void dispose() {
    _title.dispose();
    _amount.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final title = _title.text.trim();
    if (title.isEmpty) {
      showError(context, 'Say what to remind you about.');
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(reminderRepositoryProvider).create(
            title: title,
            dueAt: DateTime.now().add(Duration(days: _inDays)),
            partyId: widget.party?.id,
            amount: num.tryParse(_amount.text.trim()),
          );
      ref.invalidate(remindersProvider);
      ref.invalidate(reminderSummaryProvider);
      if (!mounted) return;
      showSuccess(context, 'Saved. You will be told when it is time.');
      Navigator.pop(context);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 4,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(context.t('Remind me'), style: theme.textTheme.titleMedium),
          if (widget.party != null)
            Text(widget.party!.name, style: theme.textTheme.bodySmall),
          const SizedBox(height: 14),
          TextField(
            controller: _title,
            autofocus: true,
            textCapitalization: TextCapitalization.sentences,
            decoration: InputDecoration(
              labelText: context.t('What should I remind you about? *'),
              hintText: context.t('Ahmed se 5000 lene hain'),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: context.t('Amount (if it is about money)'),
              prefixText: symbol,
            ),
          ),
          const SizedBox(height: 14),
          Text(context.t('When?'), style: theme.textTheme.labelLarge),
          const SizedBox(height: 6),
          // Said the way somebody would say it, not as a calendar. Picking an
          // exact date is a step nobody needs for "remind me next week".
          Wrap(
            spacing: 8,
            children: [
              for (final (label, days) in [
                ('Tomorrow', 1),
                ('In 3 days', 3),
                ('Next week', 7),
                ('In 15 days', 15),
                ('Next month', 30),
              ])
                ChoiceChip(
                  label: Text(context.t(label)),
                  selected: _inDays == days,
                  showCheckmark: false,
                  onSelected: (_) => setState(() => _inDays = days),
                ),
            ],
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _busy ? null : _save,
              child: _busy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : Text(context.t('Save')),
            ),
          ),
        ],
      ),
    );
  }
}
