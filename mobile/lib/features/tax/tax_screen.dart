import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Sales tax: the switch, the settings, and the month's figures.
///
/// Off is the honest default. Most small shops are not registered for sales
/// tax at all, and the whole screen says so plainly rather than showing an
/// output-tax column to someone who will never file a return.
class TaxScreen extends ConsumerWidget {
  const TaxScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(businessSettingsProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Sales tax'))),
      body: settings.when(
        loading: () => const ListSkeleton(),
        error: (error, _) => EmptyState(
          title: context.t('Could not load settings'),
          message: error.toString(),
          isError: true,
          actionLabel: context.t('Retry'),
          onAction: () => ref.invalidate(businessSettingsProvider),
        ),
        data: (cfg) {
          final on = cfg['fbr_enabled'] == true;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              _Switch(enabled: on),
              if (on) ...[
                SectionHeader(context.t('Rates')),
                _Rates(settings: cfg),
                SectionHeader(context.t('This month')),
                _Return(symbol: symbol),
              ] else
                Padding(
                  padding: const EdgeInsets.only(top: 24),
                  child: EmptyState(
                    title: context.t('Not registered for sales tax'),
                    message: context.t(
                        'Most small shops are not, and nothing changes on your '
                        'bills. Turn it on above if you file a monthly return '
                        'with the FBR.'),
                    icon: Icons.receipt_long_outlined,
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _Switch extends ConsumerWidget {
  const _Switch({required this.enabled});

  final bool enabled;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return AppCard(
      child: SwitchListTile(
        contentPadding: EdgeInsets.zero,
        value: enabled,
        onChanged: (value) => _toggle(context, ref, value),
        title: Text(
          context.t('I am registered for sales tax'),
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(
          context.t('Adds sales tax and further tax to your bills, and gives '
              'you the figures for the monthly return.'),
        ),
      ),
    );
  }

  Future<void> _toggle(BuildContext context, WidgetRef ref, bool value) async {
    try {
      await ref
          .read(businessRepositoryProvider)
          .updateSettings({'fbr_enabled': value});
      ref.invalidate(businessSettingsProvider);
      ref.invalidate(taxReturnProvider);
      if (context.mounted) {
        showSuccess(
          context,
          value
              ? context.t('Sales tax is on. New bills will carry it.')
              : context.t('Sales tax is off. Bills already raised are unchanged.'),
        );
      }
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Rates extends ConsumerWidget {
  const _Rates({required this.settings});

  final Map<String, dynamic> settings;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final furtherOn = settings['further_tax_enabled'] == true;

    return Column(
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              _RateRow(
                label: context.t('Sales tax'),
                value: asNum(settings['sales_tax_rate']),
                onChanged: (rate) => _save(context, ref, {'sales_tax_rate': rate}),
              ),
              const Divider(height: 20),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: furtherOn,
                onChanged: (value) =>
                    _save(context, ref, {'further_tax_enabled': value}),
                title: Text(context.t('Further tax')),
                subtitle: Text(
                  context.t('Charged on top when the buyer has no STRN'),
                ),
              ),
              if (furtherOn)
                _RateRow(
                  label: context.t('Further tax rate'),
                  value: asNum(settings['further_tax_rate']),
                  onChanged: (rate) => _save(context, ref, {'further_tax_rate': rate}),
                ),
            ],
          ),
        ),
        const SizedBox(height: 10),

        // The thing a shop is most likely not to know, said plainly.
        AppCard(
          borderColor: AppColors.warning.withValues(alpha: 0.45),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: [
              const Icon(Icons.info_outline, size: 18, color: AppColors.warning),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  context.t('A customer counts as registered only if you have '
                      'entered their STRN. An NTN on its own is income tax '
                      'registration and does not stop further tax.'),
                  style: theme.textTheme.bodySmall,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Future<void> _save(
    BuildContext context, WidgetRef ref, Map<String, dynamic> body,
  ) async {
    try {
      await ref.read(businessRepositoryProvider).updateSettings(body);
      ref.invalidate(businessSettingsProvider);
      ref.invalidate(taxReturnProvider);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _RateRow extends StatelessWidget {
  const _RateRow({
    required this.label,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final num value;
  final ValueChanged<num> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: Text(label, style: Theme.of(context).textTheme.bodyMedium)),
        SizedBox(
          width: 90,
          child: TextFormField(
            initialValue: trimZeros(value),
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            textAlign: TextAlign.right,
            decoration: const InputDecoration(
              isDense: true,
              suffixText: '%',
              contentPadding: EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            ),
            onFieldSubmitted: (raw) {
              final rate = num.tryParse(raw.trim());
              if (rate != null && rate >= 0 && rate <= 100) onChanged(rate);
            },
          ),
        ),
      ],
    );
  }
}

class _Return extends ConsumerWidget {
  const _Return({required this.symbol});

  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(taxReturnProvider);
    final month = ref.watch(taxMonthProvider);
    final theme = Theme.of(context);

    return Column(
      children: [
        Row(
          children: [
            IconButton(
              icon: const Icon(Icons.chevron_left),
              onPressed: () => ref.read(taxMonthProvider.notifier).state =
                  DateTime(month.year, month.month - 1),
            ),
            Expanded(
              child: Text(
                Fmt.monthYear(month),
                textAlign: TextAlign.center,
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
              ),
            ),
            IconButton(
              icon: const Icon(Icons.chevron_right),
              onPressed: month.isBefore(DateTime(DateTime.now().year, DateTime.now().month))
                  ? () => ref.read(taxMonthProvider.notifier).state =
                      DateTime(month.year, month.month + 1)
                  : null,
            ),
          ],
        ),
        async.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(24),
            child: CircularProgressIndicator(),
          ),
          error: (error, _) => Text(error.toString()),
          data: (figures) => Column(
            children: [
              Row(
                children: [
                  Expanded(
                    child: StatTile(
                      label: figures.owesNothing
                          ? context.t('Carried forward')
                          : context.t('Payable'),
                      value: Fmt.money(
                        figures.owesNothing ? figures.carriedForward : figures.netPayable,
                        symbol: symbol,
                        decimals: false,
                      ),
                      icon: Icons.account_balance,
                      accent: figures.owesNothing ? AppColors.success : AppColors.danger,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: StatTile(
                      label: context.t('Sales'),
                      value: Fmt.money(figures.totalSales, symbol: symbol, decimals: false),
                      icon: Icons.receipt_long_outlined,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              AppCard(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _Line('Output tax', figures.outputTax, symbol),
                    if (figures.furtherTax > 0)
                      _Line('Further tax', figures.furtherTax, symbol),
                    _Line('Input tax claimed', -figures.inputTax, symbol),
                    const Divider(height: 18),
                    _Line(
                      figures.owesNothing ? 'Carried forward' : 'Net payable',
                      figures.owesNothing ? figures.carriedForward : figures.netPayable,
                      symbol,
                      bold: true,
                    ),
                  ],
                ),
              ),

              // Stated on its own line because a shop losing this every month
              // has a reason to change supplier.
              if (figures.unclaimableInputTax > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: AppCard(
                    borderColor: AppColors.warning.withValues(alpha: 0.45),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                    child: Row(
                      children: [
                        const Icon(Icons.warning_amber_rounded,
                            size: 18, color: AppColors.warning),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            context.t(
                                '${Fmt.money(figures.unclaimableInputTax, symbol: symbol, decimals: false)} '
                                'of tax cannot be claimed — those suppliers are not '
                                'registered.'),
                            style: theme.textTheme.bodySmall,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () => _export(context, ref, month),
                icon: const Icon(Icons.download_outlined),
                label: Text(context.t('Download Annexure C')),
              ),
              const SizedBox(height: 6),
              Text(
                context.t('Karobar does not file your return — this is the '
                    'sales register to upload on IRIS yourself.'),
                textAlign: TextAlign.center,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Future<void> _export(BuildContext context, WidgetRef ref, DateTime month) async {
    try {
      final csv = await ref
          .read(taxRepositoryProvider)
          .annexureC(month: month.month, year: month.year);
      final directory = await getTemporaryDirectory();
      final file = File(
        '${directory.path}/annexure-c-${month.year}-${month.month.toString().padLeft(2, '0')}.csv',
      );
      await file.writeAsString(csv);

      if (!context.mounted) return;
      await Share.shareXFiles(
        [XFile(file.path, mimeType: 'text/csv')],
        subject: 'Annexure C',
      );
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Line extends StatelessWidget {
  const _Line(this.label, this.value, this.symbol, {this.bold = false});

  final String label;
  final num value;
  final String symbol;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(
            child: Text(
              context.t(label),
              style: bold
                  ? theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)
                  : theme.textTheme.bodyMedium
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          ),
          Text(
            Fmt.money(value, symbol: symbol),
            style: (bold ? theme.textTheme.titleSmall : theme.textTheme.bodyMedium)
                ?.copyWith(
              fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}
