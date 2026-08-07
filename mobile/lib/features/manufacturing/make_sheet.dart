import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Make a batch, having first been told what it will take.
///
/// The costing is fetched before anything is committed, because a run that
/// cannot finish must never leave half the materials consumed and no finished
/// goods to show. What is short, and by how much, is on screen before the
/// button can be pressed.
Future<void> showMakeSheet(BuildContext context, WidgetRef ref, Recipe recipe) async {
  final made = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _MakeSheet(recipe: recipe),
  );
  if (made == true) {
    ref.invalidate(recipesProvider);
    ref.invalidate(productionRunsProvider);
    ref.invalidate(itemsProvider);
    ref.invalidate(stockSummaryProvider);
  }
}

class _MakeSheet extends ConsumerStatefulWidget {
  const _MakeSheet({required this.recipe});

  final Recipe recipe;

  @override
  ConsumerState<_MakeSheet> createState() => _MakeSheetState();
}

class _MakeSheetState extends ConsumerState<_MakeSheet> {
  late final _qty = TextEditingController(text: trimZeros(widget.recipe.outputQty));
  Timer? _debounce;

  RecipeCosting? _costing;
  bool _loading = false;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _qty.addListener(_onQtyChanged);
    _fetchCosting();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _qty.dispose();
    super.dispose();
  }

  void _onQtyChanged() {
    // Debounced: a shopkeeper typing "120" would otherwise ask the server what
    // 1, then 12, then 120 would take.
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), _fetchCosting);
  }

  Future<void> _fetchCosting() async {
    final qty = num.tryParse(_qty.text.trim());
    if (qty == null || qty <= 0) {
      setState(() => _costing = null);
      return;
    }

    setState(() => _loading = true);
    try {
      final costing = await ref
          .read(manufacturingRepositoryProvider)
          .costing(widget.recipe.id, qty);
      if (mounted) setState(() => _costing = costing);
    } catch (_) {
      if (mounted) setState(() => _costing = null);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;
    final costing = _costing;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              context.t('Make ${widget.recipe.itemName}'),
              style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            Text(
              context.t('Up to ${trimZeros(widget.recipe.canMake)} with what you have'),
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 16),

            TextField(
              controller: _qty,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: context.t('How many'),
                suffixIcon: _loading
                    ? const Padding(
                        padding: EdgeInsets.all(14),
                        child: SizedBox(
                          width: 16, height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      )
                    : null,
              ),
            ),

            if (costing != null) ...[
              const SizedBox(height: 16),

              if (!costing.canMakeNow)
                AppCard(
                  borderColor: AppColors.danger.withValues(alpha: 0.5),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.error_outline,
                              size: 18, color: AppColors.danger),
                          const SizedBox(width: 8),
                          Text(
                            context.t('Not enough materials'),
                            style: theme.textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: AppColors.danger,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      for (final short in costing.shortages)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 3),
                          child: Text(
                            context.t('${short.itemName}: '
                                '${trimZeros(short.shortBy)} short'),
                            style: theme.textTheme.bodySmall,
                          ),
                        ),
                    ],
                  ),
                )
              else
                AppCard(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SectionRow(
                        label: context.t('Materials'),
                        value: Fmt.money(costing.materialCost, symbol: symbol),
                      ),
                      if (costing.wastageCost > 0)
                        SectionRow(
                          label: context.t('Wastage'),
                          value: Fmt.money(costing.wastageCost, symbol: symbol),
                        ),
                      if (costing.labourCost > 0)
                        SectionRow(
                          label: context.t('Labour'),
                          value: Fmt.money(costing.labourCost, symbol: symbol),
                        ),
                      if (costing.overheadCost > 0)
                        SectionRow(
                          label: context.t('Overhead'),
                          value: Fmt.money(costing.overheadCost, symbol: symbol),
                        ),
                      const Divider(height: 18),
                      SectionRow(
                        label: context.t('Total'),
                        value: Fmt.money(costing.totalCost, symbol: symbol),
                        bold: true,
                      ),
                      SectionRow(
                        label: context.t('Each one costs'),
                        value: Fmt.money(costing.unitCost, symbol: symbol),
                        bold: true,
                      ),
                    ],
                  ),
                ),

              const SizedBox(height: 10),
              Text(
                context.t('What it goes in at'),
                style: theme.textTheme.labelMedium,
              ),
              const SizedBox(height: 6),
              for (final need in costing.requirements)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          need.itemName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodySmall,
                        ),
                      ),
                      Text(
                        trimZeros(need.needed),
                        style: theme.textTheme.bodySmall?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: need.shortBy > 0 ? AppColors.danger : null,
                        ),
                      ),
                    ],
                  ),
                ),
            ],

            const SizedBox(height: 18),
            FilledButton(
              onPressed: (_saving || costing == null || !costing.canMakeNow)
                  ? null
                  : _make,
              child: _saving
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(context.t('Make it')),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _make() async {
    setState(() => _saving = true);
    try {
      final run = await ref.read(manufacturingRepositoryProvider).make(
            widget.recipe.id,
            num.parse(_qty.text.trim()),
          );
      if (mounted) {
        Navigator.pop(context, true);
        showSuccess(context, context.t('${run.number} made'));
      }
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}

/// A label and a figure on one line, used in the costing breakdown.
class SectionRow extends StatelessWidget {
  const SectionRow({
    super.key,
    required this.label,
    required this.value,
    this.bold = false,
  });

  final String label;
  final String value;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: bold
                  ? theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)
                  : theme.textTheme.bodyMedium
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          ),
          Text(
            value,
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
