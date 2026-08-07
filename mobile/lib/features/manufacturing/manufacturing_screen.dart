import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'make_sheet.dart';
import 'recipe_form_sheet.dart';

/// Recipes and what has been made from them.
class ManufacturingScreen extends ConsumerWidget {
  const ManufacturingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(context.t('Making things')),
          bottom: TabBar(
            tabs: [
              Tab(text: context.t('Recipes')),
              Tab(text: context.t('Made')),
            ],
          ),
        ),
        body: const TabBarView(children: [_Recipes(), _Runs()]),
      ),
    );
  }
}

class _Recipes extends ConsumerWidget {
  const _Recipes();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(recipesProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'add-recipe',
        onPressed: () => showRecipeFormSheet(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.t('New recipe')),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(recipesProvider),
        child: async.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load recipes'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(recipesProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('Nothing is made here yet'),
                  message: context.t(
                      'A recipe says what goes into one batch. Once it is set '
                      'up, making a batch takes the materials off your stock '
                      'and puts the finished goods on.'),
                  icon: Icons.blender_outlined,
                  actionLabel: context.t('New recipe'),
                  onAction: () => showRecipeFormSheet(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 90),
                  children: [
                    for (final recipe in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _RecipeCard(recipe: recipe, symbol: symbol),
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}

class _RecipeCard extends ConsumerWidget {
  const _RecipeCard({required this.recipe, required this.symbol});

  final Recipe recipe;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return AppCard(
      onTap: recipe.hasMaterials ? () => showMakeSheet(context, ref, recipe) : null,
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
                      recipe.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      context.t('${trimZeros(recipe.outputQty)} × ${recipe.itemName} '
                          'from ${recipe.components.length} materials'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(Icons.delete_outline, size: 20),
                onPressed: () => _delete(context, ref),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _Figure(
                  label: context.t('Each one costs'),
                  value: Fmt.money(recipe.unitCost, symbol: symbol),
                ),
              ),
              Expanded(
                child: _Figure(
                  label: context.t('Can make today'),
                  value: trimZeros(recipe.canMake),
                  tint: recipe.hasMaterials ? null : AppColors.danger,
                ),
              ),
            ],
          ),
          if (!recipe.hasMaterials)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                children: [
                  const Icon(Icons.inventory_2_outlined,
                      size: 14, color: AppColors.danger),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      context.t('Not enough materials on hand'),
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

  Future<void> _delete(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Delete this recipe?')),
        content: Text(
          context.t('Anything already made from it keeps the cost it was made at.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialog, false),
            child: Text(context.t('Cancel')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialog, true),
            child: Text(context.t('Delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    try {
      await ref.read(manufacturingRepositoryProvider).deleteRecipe(recipe.id);
      ref.invalidate(recipesProvider);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Runs extends ConsumerWidget {
  const _Runs();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(productionRunsProvider);
    final symbol = ref.watch(sessionProvider).symbol;
    final theme = Theme.of(context);

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(productionRunsProvider),
      child: async.when(
        loading: () => const ListSkeleton(),
        error: (error, _) => EmptyState(
          title: context.t('Could not load what was made'),
          message: error.toString(),
          isError: true,
          actionLabel: context.t('Retry'),
          onAction: () => ref.invalidate(productionRunsProvider),
        ),
        data: (rows) => rows.isEmpty
            ? EmptyState(
                title: context.t('Nothing made yet'),
                message: context.t('Batches you make show up here with what '
                    'each one cost.'),
                icon: Icons.inventory_outlined,
              )
            : ListView(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                children: [
                  for (final run in rows)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: AppCard(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 14, vertical: 12),
                        onTap: () => _undo(context, ref, run),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    '${trimZeros(run.qty)} × ${run.itemName}',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: theme.textTheme.titleSmall
                                        ?.copyWith(fontWeight: FontWeight.w700),
                                  ),
                                  Text(
                                    '${run.number}  ·  ${Fmt.dateShort(run.runDate)}',
                                    style: theme.textTheme.bodySmall?.copyWith(
                                      color: theme.colorScheme.onSurfaceVariant,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(
                                  Fmt.money(run.totalCost, symbol: symbol, decimals: false),
                                  style: theme.textTheme.titleSmall
                                      ?.copyWith(fontWeight: FontWeight.w800),
                                ),
                                Text(
                                  context.t('${Fmt.money(run.unitCost, symbol: symbol)} each'),
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
      ),
    );
  }

  Future<void> _undo(BuildContext context, WidgetRef ref, ProductionRun run) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(context.t('Undo ${run.number}?')),
        content: Text(
          context.t('The materials go back on your stock and the finished '
              'units come off. Not possible once they have been sold.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialog, false),
            child: Text(context.t('Keep it')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialog, true),
            child: Text(context.t('Undo')),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    try {
      await ref.read(manufacturingRepositoryProvider).undoRun(run.id);
      ref.invalidate(productionRunsProvider);
      ref.invalidate(recipesProvider);
      ref.invalidate(itemsProvider);
      if (context.mounted) showSuccess(context, context.t('Undone'));
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
