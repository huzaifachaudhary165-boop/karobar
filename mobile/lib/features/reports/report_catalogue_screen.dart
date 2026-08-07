import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'report_viewer_screen.dart';

/// Every report the app can produce, listed from the server.
///
/// Built from the catalogue rather than a hard-coded menu: a report added on
/// the server appears here without an app release, and a menu that drifts out
/// of step with what actually exists is how a feature becomes unreachable.
class ReportCatalogueScreen extends ConsumerStatefulWidget {
  const ReportCatalogueScreen({super.key});

  @override
  ConsumerState<ReportCatalogueScreen> createState() =>
      _ReportCatalogueScreenState();
}

class _ReportCatalogueScreenState extends ConsumerState<ReportCatalogueScreen> {
  final _search = TextEditingController();
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(reportCatalogueProvider);

    return Scaffold(
      appBar: AppBar(title: Text(context.t('All reports'))),
      body: async.when(
        loading: () => const ListSkeleton(),
        error: (error, _) => EmptyState(
          title: context.t('Could not load the report list'),
          message: error.toString(),
          isError: true,
          actionLabel: context.t('Retry'),
          onAction: () => ref.invalidate(reportCatalogueProvider),
        ),
        data: (groups) {
          final filtered = _filter(groups);
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
                child: TextField(
                  controller: _search,
                  decoration: InputDecoration(
                    hintText: context.t('Search reports'),
                    prefixIcon: const Icon(Icons.search),
                  ),
                  onChanged: (value) => setState(() => _query = value.trim()),
                ),
              ),
              Expanded(
                child: filtered.isEmpty
                    ? EmptyState(
                        title: context.t('Nothing matches'),
                        message: context.t('Try a different word.'),
                        icon: Icons.search_off,
                      )
                    : ListView(
                        padding: const EdgeInsets.only(bottom: 32),
                        children: [
                          for (final group in filtered) ...[
                            SectionHeader(context.t(group.title)),
                            for (final report in group.reports)
                              _ReportTile(report: report),
                          ],
                        ],
                      ),
              ),
            ],
          );
        },
      ),
    );
  }

  List<ReportGroup> _filter(List<ReportGroup> groups) {
    if (_query.isEmpty) return groups;
    final needle = _query.toLowerCase();

    return groups
        .map((group) => ReportGroup(
              title: group.title,
              reports: group.reports
                  .where((report) =>
                      report.name.toLowerCase().contains(needle) ||
                      report.about.toLowerCase().contains(needle))
                  .toList(),
            ))
        .where((group) => group.reports.isNotEmpty)
        .toList();
  }
}

class _ReportTile extends StatelessWidget {
  const _ReportTile({required this.report});

  final ReportEntry report;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final reachable = report.screen != null || report.endpoint != null;

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: AppCard(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        onTap: reachable ? () => _open(context) : null,
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    report.name,
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    report.about,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
            Icon(
              Icons.chevron_right,
              size: 20,
              color: reachable
                  ? null
                  : theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.4),
            ),
          ],
        ),
      ),
    );
  }

  void _open(BuildContext context) {
    // A report with a screen of its own goes there; everything else is a table
    // the generic viewer can render from its endpoint.
    final screen = report.screen;
    if (screen != null) {
      final route = _routeFor(screen);
      if (route != null) {
        context.goNamed(route);
        return;
      }
    }
    if (report.endpoint != null) {
      Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => ReportViewerScreen(report: report)),
      );
    }
  }

  String? _routeFor(String screen) => switch (screen.split('?').first) {
        'expiry' => Routes.expiry,
        'cheques' => Routes.cheques,
        'loans' => Routes.loans,
        'accounts' => Routes.accounts,
        'godowns' => Routes.godowns,
        'pricing' => Routes.pricing,
        'loyalty' => Routes.loyalty,
        'recurring' => Routes.recurring,
        'manufacturing' => Routes.manufacturing,
        'tax' => Routes.tax,
        'items' => Routes.items,
        'parties' => Routes.parties,
        _ => null,
      };
}
