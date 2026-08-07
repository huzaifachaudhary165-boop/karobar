import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// The points scheme, what it costs, and who holds the most.
class LoyaltyScreen extends ConsumerWidget {
  const LoyaltyScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(loyaltyProgramProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Loyalty points'))),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(loyaltyProgramProvider);
          ref.invalidate(loyaltyTopProvider);
        },
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load the scheme'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(loyaltyProgramProvider),
          ),
          data: (program) => ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              if (program == null)
                _NotSetUp(onStart: () => _edit(context, ref, null))
              else ...[
                _Scheme(program: program, symbol: symbol, onEdit: () => _edit(context, ref, program)),
                SectionHeader(context.t('Who holds the most')),
                _TopHolders(symbol: symbol),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _edit(
    BuildContext context, WidgetRef ref, LoyaltyProgram? existing,
  ) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SchemeForm(existing: existing),
    );
    if (saved == true) ref.invalidate(loyaltyProgramProvider);
  }
}

class _NotSetUp extends StatelessWidget {
  const _NotSetUp({required this.onStart});

  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 30),
      child: EmptyState(
        title: context.t('No points scheme'),
        message: context.t(
            'Give regular customers a reason to come back. Points are earned '
            'on every sale on their own and come off a later bill.'),
        icon: Icons.card_giftcard_outlined,
        actionLabel: context.t('Set one up'),
        onAction: onStart,
      ),
    );
  }
}

class _Scheme extends ConsumerWidget {
  const _Scheme({
    required this.program,
    required this.symbol,
    required this.onEdit,
  });

  final LoyaltyProgram program;
  final String symbol;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return Column(
      children: [
        AppCard(
          onTap: onEdit,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      program.name,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ),
                  StatusChip(
                    program.isActive ? 'paid' : 'cancelled',
                    label: program.isActive ? 'Running' : 'Paused',
                    dense: true,
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(program.earnLabel, style: theme.textTheme.bodyMedium),
              Text(
                context.t('One point is worth '
                    '${Fmt.money(program.pointValue, symbol: symbol)}'),
                style: theme.textTheme.bodyMedium,
              ),
              if (program.expiresAfterMonths != null)
                Text(
                  context.t('Points expire after ${program.expiresAfterMonths} months'),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
            ],
          ),
        ),
        const SizedBox(height: 10),

        // What the scheme costs, stated plainly. A shopkeeper setting one up
        // should see it before they hand out a tenth of their margin.
        AppCard(
          borderColor: (program.costPercent > 5 ? AppColors.warning : AppColors.success)
              .withValues(alpha: 0.45),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: [
              Icon(
                program.costPercent > 5 ? Icons.warning_amber_rounded : Icons.percent,
                size: 18,
                color: program.costPercent > 5 ? AppColors.warning : AppColors.success,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  context.t('This scheme costs ${trimZeros(program.costPercent)}% '
                      'of every sale.'),
                  style: theme.textTheme.bodySmall,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _TopHolders extends ConsumerWidget {
  const _TopHolders({required this.symbol});

  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(loyaltyTopProvider);
    final theme = Theme.of(context);

    return async.when(
      loading: () => const ListSkeleton(rows: 3),
      error: (error, _) => Text(error.toString()),
      data: (rows) => rows.isEmpty
          ? Padding(
              padding: const EdgeInsets.only(top: 20),
              child: Text(
                context.t('Nobody has points yet. They start appearing after '
                    'the next sale.'),
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            )
          : Column(
              children: [
                for (final holder in rows)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: AppCard(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      child: Row(
                        children: [
                          NameAvatar(holder.partyName, size: 36),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              holder.partyName,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.titleSmall
                                  ?.copyWith(fontWeight: FontWeight.w600),
                            ),
                          ),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                '${holder.points}',
                                style: theme.textTheme.titleSmall
                                    ?.copyWith(fontWeight: FontWeight.w800),
                              ),
                              Text(
                                Fmt.money(holder.value, symbol: symbol, decimals: false),
                                style: theme.textTheme.labelSmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}

class _SchemeForm extends ConsumerStatefulWidget {
  const _SchemeForm({this.existing});

  final LoyaltyProgram? existing;

  @override
  ConsumerState<_SchemeForm> createState() => _SchemeFormState();
}

class _SchemeFormState extends ConsumerState<_SchemeForm> {
  late final _perRupees = TextEditingController(
    text: widget.existing == null || widget.existing!.earnRate <= 0
        ? '100'
        : trimZeros((1 / widget.existing!.earnRate).roundToDouble()),
  );
  late final _pointValue = TextEditingController(
    text: trimZeros(widget.existing?.pointValue ?? 1),
  );
  late final _expiry = TextEditingController(
    text: widget.existing?.expiresAfterMonths?.toString() ?? '',
  );
  final _formKey = GlobalKey<FormState>();

  late bool _active = widget.existing?.isActive ?? true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    for (final controller in [_perRupees, _pointValue]) {
      controller.addListener(() => setState(() {}));
    }
  }

  @override
  void dispose() {
    _perRupees.dispose();
    _pointValue.dispose();
    _expiry.dispose();
    super.dispose();
  }

  /// What the scheme would cost, shown as it is typed.
  double? get _costPercent {
    final per = num.tryParse(_perRupees.text.trim());
    final value = num.tryParse(_pointValue.text.trim());
    if (per == null || per <= 0 || value == null || value < 0) return null;
    return (value / per * 100).toDouble();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;
    final cost = _costPercent;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                widget.existing == null
                    ? context.t('Set up points')
                    : context.t('Change the scheme'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),

              // Asked as "one point per how many rupees" rather than as a rate:
              // 0.01 is a number nobody thinks in, and a misplaced decimal
              // there is a scheme that gives away the shop.
              TextFormField(
                controller: _perRupees,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: context.t('One point per'),
                  prefixText: symbol,
                  helperText: context.t('How much a customer spends to earn one'),
                ),
                validator: (value) {
                  final per = num.tryParse((value ?? '').trim());
                  return per == null || per <= 0 ? context.t('Enter an amount') : null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _pointValue,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('One point is worth'),
                  prefixText: symbol,
                ),
                validator: (value) {
                  final worth = num.tryParse((value ?? '').trim());
                  return worth == null || worth < 0 ? context.t('Enter a value') : null;
                },
              ),

              if (cost != null) ...[
                const SizedBox(height: 12),
                AppCard(
                  borderColor: (cost > 5 ? AppColors.warning : AppColors.success)
                      .withValues(alpha: 0.45),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  child: Row(
                    children: [
                      Icon(
                        cost > 5 ? Icons.warning_amber_rounded : Icons.percent,
                        size: 18,
                        color: cost > 5 ? AppColors.warning : AppColors.success,
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          context.t('That is ${trimZeros(double.parse(cost.toStringAsFixed(2)))}% '
                              'of every sale.'),
                          style: theme.textTheme.bodySmall,
                        ),
                      ),
                    ],
                  ),
                ),
              ],

              const SizedBox(height: 12),
              TextFormField(
                controller: _expiry,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: context.t('Points expire after'),
                  suffixText: context.t('months'),
                  helperText: context.t('Leave empty and they never expire'),
                ),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _active,
                onChanged: (value) => setState(() => _active = value),
                title: Text(context.t('Running')),
                subtitle: Text(
                  context.t('Pausing keeps points already given'),
                ),
              ),
              const SizedBox(height: 8),
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
      ),
    );
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);

    final per = num.parse(_perRupees.text.trim());
    try {
      await ref.read(loyaltyRepositoryProvider).saveProgram({
        'earn_rate': 1 / per,
        'point_value': num.parse(_pointValue.text.trim()),
        'is_active': _active,
        if (int.tryParse(_expiry.text.trim()) != null)
          'expires_after_months': int.parse(_expiry.text.trim()),
      });
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}
