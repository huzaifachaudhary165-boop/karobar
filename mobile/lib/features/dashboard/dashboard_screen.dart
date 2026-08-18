import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/device.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import '../payments/receive_payment_sheet.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(dashboardProvider);
    final period = ref.watch(dashboardPeriodProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    // Watched here because the dashboard is the first screen after sign-in and
    // there is no scheduler on the server: this call is the whole reason a
    // repeating bill repeats. Bills going out in the shop's name is not
    // something to do silently, so the result is shown below.
    final run = ref.watch(recurringRunProvider).valueOrNull;

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(dashboardProvider),
      child: async.when(
        loading: () => const ListSkeleton(rows: 5, height: 92),
        error: (error, _) => ListView(
          children: [
            const SizedBox(height: 80),
            EmptyState(
              title: 'Could not load your figures',
              message: error.toString(),
              isError: true,
              actionLabel: context.tr('retry'),
              onAction: () => ref.invalidate(dashboardProvider),
            ),
          ],
        ),
        data: (data) =>
            _Body(data: data, period: period, symbol: symbol, run: run),
      ),
    );
  }
}

/// What the repeating bills did when the app opened.
///
/// Shown rather than left silent: invoices went out in the shop's name and
/// were posted to customer accounts. A shopkeeper finding them later with no
/// idea where they came from is the worst version of this feature.
class _RecurringNotice extends ConsumerWidget {
  const _RecurringNotice({required this.run, required this.symbol});

  final RecurringRun run;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final raised = run.created.length;
    final warn = run.problems.isNotEmpty;

    return AppCard(
      borderColor: (warn ? AppColors.danger : AppColors.success).withValues(alpha: 0.45),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () => context.goNamed(Routes.recurring),
      child: Row(
        children: [
          Icon(
            warn ? Icons.error_outline : Icons.event_repeat,
            size: 19,
            color: warn ? AppColors.danger : AppColors.success,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  raised > 0
                      ? context.t('$raised repeating bill(s) raised · '
                          '${Fmt.money(run.totalRaised, symbol: symbol, decimals: false)}')
                      : context.t('${run.reminders.length + run.problems.length} '
                          'repeating bill(s) need you'),
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  warn
                      ? context.t('One or more schedules need checking')
                      : context.t('Tap to see them'),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right, size: 20),
        ],
      ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({
    required this.data,
    required this.period,
    required this.symbol,
    this.run,
  });

  final Dashboard data;
  final String period;
  final String symbol;
  final RecurringRun? run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final strings = context.s;

    return ListView(
      padding: const EdgeInsets.only(bottom: 96),
      children: [
        // Disappears for good once the shop has a customer, an item and a bill.
        const _SetupChecklist(),

        if (run != null && !run!.isQuiet)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: _RecurringNotice(run: run!, symbol: symbol),
          ),

        _PeriodPicker(
          value: period,
          onChanged: (value) =>
              ref.read(dashboardPeriodProvider.notifier).state = value,
        ),

        // Headline figure — the number the shopkeeper opens the app for.
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
          child: _HeadlineCard(data: data, symbol: symbol),
        ),

        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Row(
            children: [
              Expanded(
                child: StatTile(
                  label: strings.get('to_collect'),
                  value: Fmt.compactMoney(data.receivable, symbol: symbol),
                  icon: Icons.call_received,
                  accent: AppColors.success,
                  // Both of these used to open the party list unfiltered, so
                  // tapping either showed the same everyone-list and looked
                  // like nothing had happened.
                  onTap: () => openTab(context, ref, HomeTab.parties,
                      partyFilter: 'receivable'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: StatTile(
                  label: strings.get('to_pay'),
                  value: Fmt.compactMoney(data.payable, symbol: symbol),
                  icon: Icons.call_made,
                  accent: AppColors.danger,
                  onTap: () => openTab(context, ref, HomeTab.parties,
                      partyFilter: 'payable'),
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: Row(
            children: [
              Expanded(
                child: StatTile(
                  label: strings.get('cash_in_hand'),
                  value: Fmt.compactMoney(data.cashInHand + data.bankBalance, symbol: symbol),
                  icon: Icons.account_balance_wallet_outlined,
                  accent: AppColors.info,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: StatTile(
                  label: strings.get('stock_value'),
                  value: Fmt.compactMoney(data.stockValue, symbol: symbol),
                  icon: Icons.inventory_2_outlined,
                  accent: AppColors.warning,
                  onTap: () =>
                      openTab(context, ref, HomeTab.items, itemFilter: 'all'),
                ),
              ),
            ],
          ),
        ),

        if (data.alerts.isNotEmpty) ...[
          SectionHeader(strings.get('needs_attention')),
          ...data.alerts.map((alert) => _AlertCard(alert: alert)),
        ],

        SectionHeader(strings.get('quick_actions')),
        const _QuickActions(),

        if (data.salesSeries.length > 1) ...[
          SectionHeader(strings.get('sales')),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: _SalesChart(points: data.salesSeries, symbol: symbol),
          ),
        ],

        if (data.topItems.isNotEmpty) ...[
          SectionHeader(
            context.t('Top items'),
            actionLabel: context.t('All items'),
            // The last raw `?tab=` in the app. Routing to a tab this way does
            // nothing when the shell is already on screen, which is the whole
            // reason these tiles read as dead.
            onAction: () => openTab(context, ref, HomeTab.items, itemFilter: 'all'),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  for (final (index, item) in data.topItems.take(5).indexed) ...[
                    if (index > 0) const Divider(height: 1),
                    ListTile(
                      dense: true,
                      leading: Text(
                        '${index + 1}',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                      title: Text(
                        item['name']?.toString() ?? '',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      subtitle: Text('${Fmt.qty(asNumOrNull(item['quantity']))} sold'),
                      trailing: MoneyText(
                        asNumOrNull(item['revenue']),
                        symbol: symbol,
                        compact: true,
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],

        if (data.recentActivity.isNotEmpty) ...[
          SectionHeader(strings.get('recent_activity')),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  for (final (index, entry) in data.recentActivity.take(6).indexed) ...[
                    if (index > 0) const Divider(height: 1),
                    _ActivityRow(entry: entry, symbol: symbol),
                  ],
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class _HeadlineCard extends StatelessWidget {
  const _HeadlineCard({required this.data, required this.symbol});

  final Dashboard data;
  final String symbol;

  /// Explains the profit figure, because on its own it is not explainable.
  ///
  /// The number here is **net** profit: what the goods earned, less expenses.
  /// Labelled only "Profit", a day of ordinary sales with the rent paid shows
  /// as a loss, and the obvious reading — "I sold everything at my sale price,
  /// how am I losing money?" — has no answer anywhere on the screen. So the
  /// card opens this.
  void _explain(BuildContext context) {
    final expenses = data.expenses.value;
    final net = data.profit.value;
    final gross = net + expenses;

    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                sheetContext.t('How this profit is worked out'),
                style: Theme.of(sheetContext).textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 4),
              Text(
                data.periodLabel,
                style: Theme.of(sheetContext).textTheme.bodySmall?.copyWith(
                      color: Theme.of(sheetContext).colorScheme.onSurfaceVariant,
                    ),
              ),
              const SizedBox(height: 18),
              _ProfitRow(
                label: sheetContext.t('Earned on goods sold'),
                hint: sheetContext.t('Sale price less what the stock cost you'),
                value: gross,
                symbol: symbol,
              ),
              _ProfitRow(
                label: sheetContext.t('Expenses'),
                hint: sheetContext.t('Rent, salaries, transport and the rest'),
                value: -expenses,
                symbol: symbol,
              ),
              const Divider(height: 26),
              _ProfitRow(
                label: sheetContext.t('Left over'),
                value: net,
                symbol: symbol,
                emphasised: true,
              ),
              const SizedBox(height: 14),
              Text(
                net < 0
                    ? sheetContext.t(
                        'This period is negative because expenses were larger '
                        'than what the goods earned. It is not a problem with '
                        'your selling prices on its own.',
                      )
                    : sheetContext.t(
                        'Expenses are already taken off, so this is what the '
                        'shop actually kept.',
                      ),
                style: Theme.of(sheetContext).textTheme.bodySmall?.copyWith(
                      color: Theme.of(sheetContext).colorScheme.onSurfaceVariant,
                      height: 1.5,
                    ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final change = data.sales.changePercent;

    return GestureDetector(
      onTap: () => _explain(context),
      child: Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [AppColors.primary, AppColors.primaryDarker],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(18),
        boxShadow: [
          BoxShadow(
            color: AppColors.primary.withValues(alpha: 0.25),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('sales'),
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.85),
              fontSize: 12,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            Fmt.money(data.sales.value, symbol: symbol, decimals: false),
            style: const TextStyle(
              color: Colors.white,
              fontSize: 32,
              fontWeight: FontWeight.w800,
              fontFeatures: [FontFeature.tabularFigures()],
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              if (change != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.20),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        change >= 0 ? Icons.arrow_upward : Icons.arrow_downward,
                        size: 12,
                        color: Colors.white,
                      ),
                      const SizedBox(width: 3),
                      Text(
                        '${change.abs().toStringAsFixed(1)}%',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
              const Spacer(),
              // "Net" is the whole point: this figure already has expenses
              // taken off it, and without the word a normal trading day with
              // the rent paid reads as "I am selling at a loss".
              _MiniStat(
                label: context.t('Net profit'),
                value: data.profit.value,
                symbol: symbol,
              ),
              const SizedBox(width: 16),
              _MiniStat(
                label: '${data.invoiceCount}',
                value: null,
                symbol: symbol,
                rawLabel: 'bills',
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Icon(Icons.info_outline,
                  size: 13, color: Colors.white.withValues(alpha: 0.75)),
              const SizedBox(width: 5),
              Text(
                context.t('Tap to see how'),
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.75),
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ],
      ),
      ),
    );
  }
}

/// One line of the profit explanation.
class _ProfitRow extends StatelessWidget {
  const _ProfitRow({
    required this.label,
    required this.value,
    required this.symbol,
    this.hint,
    this.emphasised = false,
  });

  final String label;
  final String? hint;
  final num value;
  final String symbol;
  final bool emphasised;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final negative = value < 0;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: emphasised ? FontWeight.w800 : FontWeight.w600,
                  ),
                ),
                if (hint != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    hint!,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                      fontSize: 11.5,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            Fmt.money(value, symbol: symbol, decimals: false),
            style: theme.textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w800,
              fontSize: emphasised ? 16 : 14,
              color: negative
                  ? AppColors.onSoftTint(AppColors.danger, theme.brightness)
                  : (emphasised
                      ? AppColors.onSoftTint(AppColors.success, theme.brightness)
                      : null),
            ),
          ),
        ],
      ),
    );
  }
}

class _MiniStat extends StatelessWidget {
  const _MiniStat({
    required this.label,
    required this.value,
    required this.symbol,
    this.rawLabel,
  });

  final String label;
  final num? value;
  final String symbol;
  final String? rawLabel;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          value == null ? label : Fmt.compactMoney(value, symbol: symbol),
          style: const TextStyle(
            color: Colors.white,
            fontSize: 15,
            fontWeight: FontWeight.w800,
          ),
        ),
        Text(
          rawLabel ?? label,
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.8),
            fontSize: 10,
          ),
        ),
      ],
    );
  }
}

class _PeriodPicker extends StatelessWidget {
  const _PeriodPicker({required this.value, required this.onChanged});

  final String value;
  final ValueChanged<String> onChanged;

  static const _options = {
    'today': 'Today',
    'this_week': 'This week',
    'this_month': 'This month',
    'last_month': 'Last month',
    'this_year': 'This year',
  };

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 54,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        children: [
          for (final entry in _options.entries) ...[
            ChoiceChip(
              label: Text(entry.value),
              selected: value == entry.key,
              onSelected: (_) => onChanged(entry.key),
              showCheckmark: false,
            ),
            const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

class _QuickActions extends ConsumerWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final strings = context.s;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: GridView.count(
        crossAxisCount: 4,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        // A fixed aspect ratio breaks as soon as the phone's font size changes:
        // the cell width is unaffected but the label grows, and the tile spills.
        // Sizing by content instead keeps it right at any text scale.
        mainAxisExtent: ActionTile.extentFor(context),
        children: [
          ActionTile(
            icon: Icons.receipt_long,
            label: strings.get('new_sale'),
            onTap: () => context.goNamed(
              Routes.invoiceForm,
              queryParameters: {'type': 'sale'},
            ),
          ),
          ActionTile(
            icon: Icons.shopping_bag_outlined,
            label: strings.get('new_purchase'),
            color: AppColors.info,
            onTap: () => context.goNamed(
              Routes.invoiceForm,
              queryParameters: {'type': 'purchase'},
            ),
          ),
          ActionTile(
            icon: Icons.payments_outlined,
            label: strings.get('receive_payment'),
            color: AppColors.success,
            // Records the payment here. Sending the shopkeeper to the party
            // list — which is what this did, filtered or not — is the app
            // asking them to go and find the feature themselves, while they
            // are standing at the counter holding the cash.
            onTap: () => showReceivePaymentSheet(context, ref),
          ),
          ActionTile(
            icon: Icons.document_scanner_outlined,
            label: strings.get('scan_bill'),
            color: AppColors.warning,
            // Bill scanning runs on-device and is mobile-only, so on a desktop
            // the tile says why rather than opening a screen that cannot work.
            onTap: () => Device.canReadBills
                ? context.goNamed(Routes.scan)
                : showError(context, 'Bill scanning ${Device.unavailableHere.toLowerCase()}'),
          ),
          ActionTile(
            icon: Icons.alarm,
            label: strings.get('reminders'),
            color: AppColors.warning,
            onTap: () => context.goNamed(Routes.reminders),
          ),
          ActionTile(
            icon: Icons.calculate_outlined,
            label: strings.get('calculator'),
            color: AppColors.info,
            // Here because leaving Karobar to do arithmetic is how a
            // half-finished bill gets lost, and because a shopkeeper who has
            // to open a second app to work out a rate stops trusting that this
            // one covers their day.
            // The whole module, not just the keypad — margin, discounts, tax
            // and the units a shop here buys in. The keypad is one tab of it.
            onTap: () => context.goNamed(Routes.calculator),
          ),
          ActionTile(
            icon: Icons.person_add_outlined,
            label: strings.get('add_customer'),
            onTap: () => context.goNamed(Routes.partyForm),
          ),
          ActionTile(
            icon: Icons.add_box_outlined,
            label: strings.get('add_item'),
            color: AppColors.info,
            onTap: () => context.goNamed(Routes.itemForm),
          ),
          ActionTile(
            icon: Icons.request_quote_outlined,
            label: 'Quotation',
            color: AppColors.success,
            onTap: () => context.goNamed(
              Routes.invoiceForm,
              queryParameters: {'type': 'quotation'},
            ),
          ),
          ActionTile(
            icon: Icons.insights_outlined,
            label: strings.get('reports'),
            color: AppColors.warning,
            onTap: () => context.goNamed(Routes.reports),
          ),
        ],
      ),
    );
  }
}

class _AlertCard extends ConsumerWidget {
  const _AlertCard({required this.alert});

  final Map<String, dynamic> alert;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final severity = alert['severity']?.toString() ?? 'info';
    final (tint, icon) = switch (severity) {
      'warning' => (AppColors.warning, Icons.warning_amber_rounded),
      'critical' => (AppColors.danger, Icons.error_outline),
      _ => (AppColors.info, Icons.info_outline),
    };

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
      child: AppCard(
        borderColor: tint.withValues(alpha: 0.35),
        color: tint.withValues(alpha: 0.06),
        // Every alert carries a route *and a filter*, and the filter was being
        // dropped: "1 item running low" opened the full item list rather than
        // the one item to reorder, so the card read as a dead button. An
        // unrecognised route did nothing at all, which is worse.
        onTap: () {
          final action = (alert['action'] as Map?) ?? const {};
          final route = action['route']?.toString();
          final filter = action['filter']?.toString();

          switch (route) {
            case '/invoices':
              openTab(context, ref, HomeTab.invoices,
                  voucherType: 'sale', voucherFilter: filter ?? 'all');
            case '/items':
              openTab(context, ref, HomeTab.items, itemFilter: filter ?? 'all');
            case '/quotations':
              openTab(context, ref, HomeTab.invoices,
                  voucherType: 'quotation', voucherFilter: 'all');
            case '/parties':
              openTab(context, ref, HomeTab.parties, partyFilter: filter ?? 'all');
            default:
              // Never nothing. A card that looks tappable must go somewhere.
              openTab(context, ref, HomeTab.dashboard);
          }
        },
        child: Row(
          children: [
            Icon(icon, color: tint, size: 22),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    alert['title']?.toString() ?? '',
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
                  ),
                  if (alert['body'] != null) ...[
                    const SizedBox(height: 2),
                    Text(
                      alert['body'].toString(),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ],
              ),
            ),
            const Icon(Icons.chevron_right, size: 18),
          ],
        ),
      ),
    );
  }
}

class _ActivityRow extends StatelessWidget {
  const _ActivityRow({required this.entry, required this.symbol});

  final Map<String, dynamic> entry;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final type = entry['type']?.toString() ?? '';
    final isIncoming = type == 'sale' || type == 'payment_in';
    final fromAi = entry['source'] == 'ai' || entry['source'] == 'ocr';

    return ListTile(
      dense: true,
      leading: CircleAvatar(
        radius: 17,
        backgroundColor:
            (isIncoming ? AppColors.success : AppColors.info).withValues(alpha: 0.12),
        child: Icon(
          switch (type) {
            'sale' => Icons.receipt_long,
            'purchase' => Icons.shopping_bag_outlined,
            'payment_in' => Icons.call_received,
            'payment_out' => Icons.call_made,
            _ => Icons.description_outlined,
          },
          size: 16,
          color: isIncoming ? AppColors.success : AppColors.info,
        ),
      ),
      title: Row(
        children: [
          Flexible(
            child: Text(
              entry['party']?.toString() ?? 'Walk-in',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
            ),
          ),
          if (fromAi) ...[
            const SizedBox(width: 6),
            const Icon(Icons.auto_awesome, size: 12, color: AppColors.primary),
          ],
        ],
      ),
      subtitle: Text(
        '${entry['number'] ?? ''} · ${Fmt.relative(Fmt.parseDate(entry['date']?.toString()))}',
        style: const TextStyle(fontSize: 11),
      ),
      trailing: MoneyText(
        asNumOrNull(entry['amount']),
        symbol: symbol,
        compact: true,
        style: Theme.of(context).textTheme.titleSmall,
      ),
      onTap: () {
        final id = entry['id']?.toString();
        if (id != null && (type == 'sale' || type == 'purchase')) {
          context.goNamed(Routes.invoiceDetail, pathParameters: {'id': id});
        }
      },
    );
  }
}

class _SalesChart extends StatelessWidget {
  const _SalesChart({required this.points, required this.symbol});

  final List<SeriesPoint> points;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final maxValue = points.map((p) => p.value).fold<num>(0, (a, b) => a > b ? a : b);
    final scheme = Theme.of(context).colorScheme;

    return AppCard(
      padding: const EdgeInsets.fromLTRB(8, 20, 16, 8),
      child: SizedBox(
        height: 180,
        child: LineChart(
          LineChartData(
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              horizontalInterval: maxValue <= 0 ? 1 : maxValue / 3,
              getDrawingHorizontalLine: (_) =>
                  FlLine(color: scheme.outlineVariant, strokeWidth: 1),
            ),
            titlesData: FlTitlesData(
              rightTitles: const AxisTitles(),
              topTitles: const AxisTitles(),
              leftTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 46,
                  interval: maxValue <= 0 ? 1 : maxValue / 2,
                  getTitlesWidget: (value, _) => Text(
                    Fmt.compactMoney(value, symbol: ''),
                    style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant),
                  ),
                ),
              ),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 26,
                  interval: (points.length / 4).ceilToDouble().clamp(1, 999),
                  getTitlesWidget: (value, _) {
                    final index = value.toInt();
                    if (index < 0 || index >= points.length) return const SizedBox.shrink();
                    final label = points[index].label;
                    return Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(
                        label.length > 5 ? label.substring(label.length - 5) : label,
                        style: TextStyle(fontSize: 9, color: scheme.onSurfaceVariant),
                      ),
                    );
                  },
                ),
              ),
            ),
            borderData: FlBorderData(show: false),
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                getTooltipItems: (spots) => spots
                    .map(
                      (spot) => LineTooltipItem(
                        Fmt.money(spot.y, symbol: symbol, decimals: false),
                        const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 12,
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
            lineBarsData: [
              LineChartBarData(
                spots: [
                  for (final (index, point) in points.indexed)
                    FlSpot(index.toDouble(), point.value.toDouble()),
                ],
                isCurved: true,
                curveSmoothness: 0.28,
                color: AppColors.primary,
                barWidth: 3,
                dotData: FlDotData(show: points.length <= 14),
                belowBarData: BarAreaData(
                  show: true,
                  gradient: LinearGradient(
                    colors: [
                      AppColors.primary.withValues(alpha: 0.28),
                      AppColors.primary.withValues(alpha: 0.02),
                    ],
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Three things a brand-new shop needs before the numbers above mean anything.
/// It renders nothing once all three are done, so an established shop never
/// sees it.
class _SetupChecklist extends ConsumerWidget {
  const _SetupChecklist();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // valueOrNull, not maybeWhen(orElse: null). Riverpod keeps the previous
    // value on an AsyncLoading raised by a refresh, and this card is refreshed
    // by every write — so treating "loading" as "no data" made it vanish and
    // reappear on each screen change, which reads as the app glitching rather
    // than as data arriving.
    final progress = ref.watch(setupProgressProvider).valueOrNull;
    if (progress == null || progress.isComplete) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final accent = AppColors.onSoftTint(AppColors.primary, theme.brightness);

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: AppCard(
        color: AppColors.softTint(AppColors.primary, theme.brightness),
        borderColor: AppColors.primary.withValues(alpha: 0.35),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.rocket_launch_outlined, size: 19, color: accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Set up your shop',
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ),
                Text(
                  '${progress.done} of 3',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: accent,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                value: progress.done / 3,
                minHeight: 5,
                // Not Colors.white: on the dark card that painted a bright bar
                // across the whole width, so an empty checklist looked complete.
                backgroundColor: AppColors.primary.withValues(alpha: 0.18),
                valueColor: const AlwaysStoppedAnimation(AppColors.primary),
              ),
            ),
            const SizedBox(height: 6),
            _ChecklistStep(
              done: progress.hasParty,
              label: 'Add your first customer',
              onTap: () => context.goNamed(Routes.partyForm),
            ),
            _ChecklistStep(
              done: progress.hasItem,
              label: 'Add an item you sell',
              onTap: () => context.goNamed(Routes.itemForm),
            ),
            _ChecklistStep(
              done: progress.hasInvoice,
              label: 'Make your first bill',
              // 'sale', not 'sale_invoice' — the latter is not a voucher type
              // the API accepts, so this step opened a form that could not save.
              onTap: () => context.goNamed(
                Routes.invoiceForm,
                queryParameters: {'type': 'sale'},
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ChecklistStep extends StatelessWidget {
  const _ChecklistStep({
    required this.done,
    required this.label,
    required this.onTap,
  });

  final bool done;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      onTap: done ? null : onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: Row(
          children: [
            Icon(
              done ? Icons.check_circle : Icons.radio_button_unchecked,
              size: 18,
              color: done ? AppColors.success : AppColors.primary,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                label,
                style: theme.textTheme.bodyMedium?.copyWith(
                  decoration: done ? TextDecoration.lineThrough : null,
                  color: done ? theme.colorScheme.onSurfaceVariant : null,
                  fontWeight: done ? FontWeight.w400 : FontWeight.w600,
                ),
              ),
            ),
            if (!done)
              const Icon(Icons.chevron_right, size: 18, color: AppColors.primary),
          ],
        ),
      ),
    );
  }
}
