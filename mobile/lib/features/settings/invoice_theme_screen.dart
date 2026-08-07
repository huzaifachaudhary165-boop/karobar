import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Choose how the shop's bills look.
///
/// Grouped by what the shop is printing on, because that is how the choice is
/// actually made — a shop with a till roll and a shop with A4 sticker paper are
/// not browsing the same list. Each one can be previewed before it is chosen:
/// a name like "Modern — indigo side stripe" tells nobody whether their
/// forty-line bill will fit on one page.
class InvoiceThemeScreen extends ConsumerWidget {
  const InvoiceThemeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themes = ref.watch(invoiceThemesProvider);
    final settings = ref.watch(businessSettingsProvider);
    final current = settings.valueOrNull?['invoice_template']?.toString();

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Invoice look'))),
      body: themes.when(
        loading: () => const ListSkeleton(),
        error: (error, _) => EmptyState(
          title: context.t('Could not load the looks'),
          message: error.toString(),
          isError: true,
          actionLabel: context.t('Retry'),
          onAction: () => ref.invalidate(invoiceThemesProvider),
        ),
        data: (rows) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            for (final group in _grouped(rows).entries) ...[
              SectionHeader(context.t(group.key)),
              for (final theme in group.value)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _ThemeCard(
                    theme: theme,
                    selected: theme.key == current,
                    onChoose: () => _choose(context, ref, theme),
                    onPreview: () => _preview(context, ref, theme),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }

  /// Papers first, because the paper is the thing a shop cannot change.
  Map<String, List<InvoiceTheme>> _grouped(List<InvoiceTheme> rows) {
    final groups = <String, List<InvoiceTheme>>{
      'Till roll': [],
      'A4 — full page': [],
      'Smaller paper': [],
    };
    for (final theme in rows) {
      if (theme.isRoll) {
        groups['Till roll']!.add(theme);
      } else if (theme.paper == 'A4') {
        groups['A4 — full page']!.add(theme);
      } else {
        groups['Smaller paper']!.add(theme);
      }
    }
    groups.removeWhere((_, value) => value.isEmpty);
    return groups;
  }

  Future<void> _choose(BuildContext context, WidgetRef ref, InvoiceTheme theme) async {
    try {
      await ref
          .read(businessRepositoryProvider)
          .updateSettings({'invoice_template': theme.key});
      ref.invalidate(businessSettingsProvider);
      if (context.mounted) {
        showSuccess(context, context.t('Bills will print in ${theme.name}'));
      }
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  /// Renders a sample bill and hands it to the system viewer.
  ///
  /// Shared as a file rather than drawn in-app: the same sheet then goes
  /// straight to a printer from the share menu, which is the only way to find
  /// out whether a layout actually fits the paper.
  Future<void> _preview(BuildContext context, WidgetRef ref, InvoiceTheme theme) async {
    try {
      final html = await ref.read(businessRepositoryProvider).invoicePreview(theme.key);
      final directory = await getTemporaryDirectory();
      final file = File('${directory.path}/karobar-invoice-${theme.key}.html');
      await file.writeAsString(html);

      if (!context.mounted) return;
      await Share.shareXFiles(
        [XFile(file.path, mimeType: 'text/html')],
        subject: theme.name,
      );
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _ThemeCard extends StatelessWidget {
  const _ThemeCard({
    required this.theme,
    required this.selected,
    required this.onChoose,
    required this.onPreview,
  });

  final InvoiceTheme theme;
  final bool selected;
  final VoidCallback onChoose;
  final VoidCallback onPreview;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final accent = Color(theme.accentValue);

    return AppCard(
      onTap: onChoose,
      borderColor: selected ? AppColors.primary : null,
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
      child: Row(
        children: [
          _Swatch(layout: theme.layout, accent: accent),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  theme.name,
                  maxLines: 2,
                  style: text.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  [
                    theme.paper,
                    if (theme.density != 'regular') theme.density,
                  ].join('  ·  '),
                  style: text.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          if (selected)
            const Padding(
              padding: EdgeInsets.only(right: 4),
              child: Icon(Icons.check_circle, size: 20, color: AppColors.primary),
            ),
          IconButton(
            icon: const Icon(Icons.visibility_outlined, size: 20),
            tooltip: context.t('Preview'),
            onPressed: onPreview,
          ),
        ],
      ),
    );
  }
}

/// A thumbnail of the layout, drawn rather than fetched.
///
/// A real rendered preview per card would be twenty-six server round trips to
/// fill one screen. The shape is what distinguishes these — where the colour
/// sits and how dense the rows are — and that can be drawn in a few lines.
class _Swatch extends StatelessWidget {
  const _Swatch({required this.layout, required this.accent});

  final String layout;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final line = Theme.of(context).colorScheme.onSurfaceVariant.withValues(alpha: 0.35);

    return Container(
      width: 40,
      height: 52,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerLowest,
        border: Border.all(color: line.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (layout == 'band')
            Container(height: 12, color: accent)
          else if (layout == 'letterhead')
            const SizedBox(height: 16)
          else if (layout == 'roll')
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              child: Container(height: 2, color: line),
            )
          else
            const SizedBox(height: 8),
          Expanded(
            child: Row(
              children: [
                if (layout == 'sidebar') Container(width: 4, color: accent),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(4, 3, 4, 4),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (layout == 'letterhead' || layout == 'plain')
                          Padding(
                            padding: const EdgeInsets.only(bottom: 3),
                            child: Container(height: 1.5, color: accent),
                          ),
                        for (var i = 0; i < 4; i++)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 2.5),
                            child: Container(
                              height: 1.5,
                              color: line,
                              margin: EdgeInsets.only(right: i == 3 ? 14 : 0),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
