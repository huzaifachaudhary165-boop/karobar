import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Renders whatever a report endpoint returns.
///
/// Deliberately generic. A report added on the server should appear in the app
/// without a matching screen being written for it, and the alternative — one
/// screen per report — is thirty-seven files that all do the same thing and
/// drift apart one at a time.
///
/// The shape it understands is the one every report here uses: a few top-level
/// figures, and one list of rows.
class ReportViewerScreen extends ConsumerWidget {
  const ReportViewerScreen({super.key, required this.report});

  final ReportEntry report;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(reportDataProvider(report.endpoint!));
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(title: Text(report.name)),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(reportDataProvider(report.endpoint!)),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load this report'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(reportDataProvider(report.endpoint!)),
          ),
          data: (data) => _Body(data: data, symbol: symbol, about: report.about),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.data, required this.symbol, required this.about});

  final Map<String, dynamic> data;
  final String symbol;
  final String about;

  /// Keys that describe the request rather than the answer.
  static const _skip = {'start', 'end', 'days', 'receivable', 'enabled'};

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = _rows();
    final figures = _figures();

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      children: [
        Text(
          about,
          style: theme.textTheme.bodySmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 12),

        if (figures.isNotEmpty)
          AppCard(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final entry in figures)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            _humanise(entry.key),
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ),
                        Text(
                          _format(entry.key, entry.value),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),

        if (rows.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 40),
            child: EmptyState(
              title: context.t('Nothing to show'),
              message: context.t('There is no data for this period yet.'),
              icon: Icons.bar_chart_outlined,
            ),
          )
        else ...[
          const SizedBox(height: 6),
          SectionHeader(context.t('${rows.length} rows')),
          for (final row in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _Row(row: row, symbol: symbol),
            ),
        ],
      ],
    );
  }

  /// The one list in the response, whatever it happens to be called.
  List<Map<String, dynamic>> _rows() {
    for (final value in data.values) {
      if (value is List && value.isNotEmpty && value.first is Map) {
        return value.map((e) => Map<String, dynamic>.from(e as Map)).toList();
      }
    }
    return const [];
  }

  List<MapEntry<String, dynamic>> _figures() => data.entries
      .where((entry) =>
          entry.value is! List &&
          entry.value is! Map &&
          entry.value != null &&
          !_skip.contains(entry.key))
      .toList();

  String _format(String key, dynamic value) {
    if (value is bool) return value ? 'Yes' : 'No';
    if (value is num || (value is String && num.tryParse(value) != null)) {
      final amount = asNum(value);
      // Percentages and counts are not money, and printing "Rs 12" for a
      // twelve-percent margin is worse than useless.
      if (key.contains('percent')) return '${trimZeros(amount)}%';
      if (key.contains('count') || key.endsWith('_qty')) return trimZeros(amount);
      return Fmt.money(amount, symbol: symbol, decimals: false);
    }
    return value.toString();
  }

  static String _humanise(String key) {
    final words = key.replaceAll('_', ' ').trim();
    return words.isEmpty ? key : words[0].toUpperCase() + words.substring(1);
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.row, required this.symbol});

  final Map<String, dynamic> row;
  final String symbol;

  /// The first text-like field is the row's name; ids are never it.
  static const _idish = {'id', 'item_id', 'party_id', 'user_id', 'category_id'};

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = _title();
    final rest = row.entries
        .where((entry) =>
            entry.key != title.key &&
            !_idish.contains(entry.key) &&
            entry.value != null &&
            entry.value is! List &&
            entry.value is! Map)
        .take(4)
        .toList();

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            title.value?.toString() ?? '—',
            maxLines: 2,
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 16,
            runSpacing: 4,
            children: [
              for (final entry in rest)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      _Body._humanise(entry.key),
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                    Text(
                      _value(entry.key, entry.value),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                        fontFeatures: const [FontFeature.tabularFigures()],
                      ),
                    ),
                  ],
                ),
            ],
          ),
        ],
      ),
    );
  }

  MapEntry<String, dynamic> _title() {
    for (final key in ['item_name', 'party_name', 'category', 'label', 'mode',
        'number', 'name']) {
      if (row.containsKey(key) && row[key] != null) {
        return MapEntry(key, row[key]);
      }
    }
    return row.entries.first;
  }

  String _value(String key, dynamic value) {
    if (value is bool) return value ? 'Yes' : 'No';
    if (value is num || (value is String && num.tryParse(value) != null)) {
      final amount = asNum(value);
      if (key.contains('percent')) return '${trimZeros(amount)}%';
      if (key.contains('count') ||
          key.contains('qty') ||
          key == 'received' ||
          key == 'issued' ||
          key == 'closing' ||
          key.contains('days')) {
        return trimZeros(amount);
      }
      return Fmt.money(amount, symbol: symbol, decimals: false);
    }
    if (value is String && value.length == 10 && value.contains('-')) {
      return Fmt.dateShort(DateTime.tryParse(value));
    }
    return value.toString();
  }
}
