import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Reports plus AI-written insights over the same figures.
class ReportsScreen extends ConsumerStatefulWidget {
  const ReportsScreen({super.key});

  @override
  ConsumerState<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends ConsumerState<ReportsScreen> {
  String _period = 'this_month';
  Future<Map<String, dynamic>>? _profitLoss;
  Future<Map<String, dynamic>>? _ageing;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    final repository = ref.read(reportRepositoryProvider);
    setState(() {
      _profitLoss = repository.profitLoss(period: _period);
      _ageing = repository.ageing();
    });
  }

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Reports')),
        actions: [
          PopupMenuButton<String>(
            icon: const Icon(Icons.calendar_month_outlined),
            onSelected: (value) {
              setState(() => _period = value);
              _reload();
            },
            itemBuilder: (_) => [
              PopupMenuItem(value: 'this_month', child: Text(context.t('This month'))),
              PopupMenuItem(value: 'last_month', child: Text(context.t('Last month'))),
              PopupMenuItem(value: 'this_quarter', child: Text(context.t('This quarter'))),
              PopupMenuItem(value: 'this_year', child: Text(context.t('This year'))),
              PopupMenuItem(value: 'fy', child: Text(context.t('Financial year'))),
            ],
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          _reload();
          ref.invalidate(insightsProvider);
        },
        child: ListView(
          padding: const EdgeInsets.only(bottom: 32),
          children: [
            const SectionHeader('AI insights'),
            const _Insights(),
            const SectionHeader('Profit & loss'),
            _ProfitLoss(future: _profitLoss, symbol: symbol),
            const SectionHeader('Money to collect'),
            _Ageing(future: _ageing, symbol: symbol),
          ],
        ),
      ),
    );
  }
}

class _Insights extends ConsumerWidget {
  const _Insights();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(insightsProvider);

    return async.when(
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(horizontal: 16),
        child: AppCard(
          child: Row(
            children: [
              SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
              SizedBox(width: 14),
              Text('Looking at your figures…'),
            ],
          ),
        ),
      ),
      error: (error, _) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: AppCard(
          child: Row(
            children: [
              const Icon(Icons.auto_awesome_outlined, size: 18),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Insights are unavailable right now.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              TextButton(
                onPressed: () => ref.invalidate(insightsProvider),
                child: Text(context.t('Retry')),
              ),
            ],
          ),
        ),
      ),
      data: (insights) => insights.isEmpty
          ? const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: AppCard(child: Text('Nothing notable in this period.')),
            )
          : Column(
              children: [
                for (final insight in insights)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                    child: _InsightCard(insight: insight),
                  ),
              ],
            ),
    );
  }
}

class _InsightCard extends StatelessWidget {
  const _InsightCard({required this.insight});

  final Insight insight;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (tint, icon) = switch (insight.severity) {
      'critical' => (AppColors.danger, Icons.error_outline),
      'warning' => (AppColors.warning, Icons.warning_amber_rounded),
      _ => switch (insight.kind) {
          'win' => (AppColors.success, Icons.celebration_outlined),
          'suggestion' => (AppColors.info, Icons.lightbulb_outline),
          _ => (AppColors.primary, Icons.insights_outlined),
        },
    };

    return AppCard(
      borderColor: tint.withValues(alpha: 0.28),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(7),
            decoration: BoxDecoration(
              color: tint.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(icon, size: 16, color: tint),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  insight.title,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 4),
                Text(
                  insight.body,
                  style: theme.textTheme.bodySmall?.copyWith(height: 1.4),
                ),
                if (insight.action?['text'] != null) ...[
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Icon(Icons.arrow_forward, size: 12, color: tint),
                      const SizedBox(width: 5),
                      Expanded(
                        child: Text(
                          insight.action!['text'].toString(),
                          style: theme.textTheme.labelSmall
                              ?.copyWith(color: tint, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ProfitLoss extends StatelessWidget {
  const _ProfitLoss({required this.future, required this.symbol});

  final Future<Map<String, dynamic>>? future;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: FutureBuilder<Map<String, dynamic>>(
        future: future,
        builder: (_, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const AppCard(
              child: SizedBox(
                height: 120,
                child: Center(child: CircularProgressIndicator()),
              ),
            );
          }
          if (snapshot.hasError) {
            return AppCard(child: Text('Could not load: ${snapshot.error}'));
          }

          final data = snapshot.data ?? const {};
          final netProfit = asNum(data['net_profit']);

          return AppCard(
            child: Column(
              children: [
                _line(context, 'Sales', asNumOrNull(data['net_sales']), symbol),
                _line(context, 'Cost of goods sold', -(asNum(data['cost_of_goods_sold'])),
                    symbol),
                const Divider(height: 18),
                _line(context, 'Gross profit', asNumOrNull(data['gross_profit']), symbol,
                    emphasise: true),
                const SizedBox(height: 6),
                _line(context, 'Expenses', -(asNum(data['total_expenses'])), symbol),
                const Divider(height: 18),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Net profit',
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        MoneyText(
                          netProfit,
                          symbol: symbol,
                          decimals: false,
                          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                                fontWeight: FontWeight.w800,
                                color: netProfit >= 0 ? AppColors.success : AppColors.danger,
                              ),
                        ),
                        Text(
                          '${Fmt.qty(asNumOrNull(data['net_margin_percent']))}% margin',
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ],
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _line(
    BuildContext context,
    String label,
    num? value,
    String symbol, {
    bool emphasise = false,
  }) {
    final theme = Theme.of(context);
    final style = emphasise
        ? theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)
        : theme.textTheme.bodyMedium;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: style),
          MoneyText(value, symbol: symbol, decimals: false, style: style),
        ],
      ),
    );
  }
}

class _Ageing extends StatelessWidget {
  const _Ageing({required this.future, required this.symbol});

  final Future<Map<String, dynamic>>? future;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: FutureBuilder<Map<String, dynamic>>(
        future: future,
        builder: (_, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const AppCard(
              child: SizedBox(
                height: 100,
                child: Center(child: CircularProgressIndicator()),
              ),
            );
          }

          final data = snapshot.data ?? const {};
          final buckets = (data['buckets'] as List?) ?? const [];
          final parties = (data['parties'] as List?) ?? const [];

          return Column(
            children: [
              AppCard(
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          'Total outstanding',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        MoneyText(
                          asNumOrNull(data['total']),
                          symbol: symbol,
                          decimals: false,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                fontWeight: FontWeight.w800,
                              ),
                        ),
                      ],
                    ),
                    const Divider(height: 20),
                    for (final raw in buckets)
                      Builder(
                        builder: (_) {
                          final bucket = Map<String, dynamic>.from(raw as Map);
                          final label = bucket['label']?.toString() ?? '';
                          final overdue = label != 'current';
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(
                                  label == 'current' ? 'Not yet due' : '$label days',
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                                Text(
                                  Fmt.money(
                                    asNumOrNull(bucket['amount']),
                                    symbol: symbol,
                                    decimals: false,
                                  ),
                                  style: TextStyle(
                                    fontWeight: FontWeight.w600,
                                    fontSize: 13,
                                    color: overdue ? AppColors.danger : null,
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                  ],
                ),
              ),
              if (parties.isNotEmpty) ...[
                const SizedBox(height: 10),
                AppCard(
                  padding: EdgeInsets.zero,
                  child: Column(
                    children: [
                      for (final (index, raw) in parties.take(6).indexed) ...[
                        if (index > 0) const Divider(height: 1),
                        Builder(
                          builder: (_) {
                            final party = Map<String, dynamic>.from(raw as Map);
                            return ListTile(
                              dense: true,
                              leading: NameAvatar(
                                party['party_name']?.toString() ?? '?',
                                size: 34,
                              ),
                              title: Text(
                                party['party_name']?.toString() ?? '',
                                style: const TextStyle(fontWeight: FontWeight.w600),
                              ),
                              subtitle: Text('${party['invoice_count'] ?? 0} unpaid bill(s)'),
                              trailing: MoneyText(
                                asNumOrNull(party['total']),
                                symbol: symbol,
                                decimals: false,
                                compact: true,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.danger,
                                ),
                              ),
                            );
                          },
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ],
          );
        },
      ),
    );
  }
}
