import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Write down what goes into one batch.
Future<void> showRecipeFormSheet(BuildContext context, WidgetRef ref) async {
  final saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const _RecipeForm(),
  );
  if (saved == true) ref.invalidate(recipesProvider);
}

class _RecipeForm extends ConsumerStatefulWidget {
  const _RecipeForm();

  @override
  ConsumerState<_RecipeForm> createState() => _RecipeFormState();
}

class _RecipeFormState extends ConsumerState<_RecipeForm> {
  final _name = TextEditingController();
  final _output = TextEditingController(text: '1');
  final _labour = TextEditingController();
  final _wastage = TextEditingController();
  final _finishedSearch = TextEditingController();
  final _materialSearch = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  Item? _finished;
  final _materials = <({Item item, num qty})>[];

  List<Item> _finishedResults = const [];
  List<Item> _materialResults = const [];
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _output.dispose();
    _labour.dispose();
    _wastage.dispose();
    _finishedSearch.dispose();
    _materialSearch.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;

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
                context.t('New recipe'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),

              TextFormField(
                controller: _name,
                autofocus: true,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: context.t('Name'),
                  hintText: context.t('Rusk tray, 1kg rice pack'),
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? context.t('Give it a name') : null,
              ),
              const SizedBox(height: 12),

              _Picker(
                controller: _finishedSearch,
                label: context.t('What it makes'),
                results: _finishedResults,
                onSearch: (query) => _search(query, forMaterial: false),
                onPicked: (item) => setState(() {
                  _finished = item;
                  _finishedSearch.text = item.name;
                  _finishedResults = const [];
                }),
              ),
              const SizedBox(height: 12),

              // Asked per batch, not per unit: forty rusks from one tray is a
              // number that can be checked against the recipe on the wall.
              TextFormField(
                controller: _output,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('How many one batch makes'),
                  suffixText: _finished?.unitLabel,
                ),
                validator: (value) {
                  final qty = num.tryParse((value ?? '').trim());
                  return qty == null || qty <= 0 ? context.t('Enter a number') : null;
                },
              ),

              SectionHeader(context.t('What goes in')),
              for (final (index, material) in _materials.indexed)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: AppCard(
                    padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            material.item.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodyMedium,
                          ),
                        ),
                        SizedBox(
                          width: 70,
                          child: TextFormField(
                            initialValue: trimZeros(material.qty),
                            keyboardType:
                                const TextInputType.numberWithOptions(decimal: true),
                            textAlign: TextAlign.right,
                            decoration: InputDecoration(
                              isDense: true,
                              suffixText: material.item.unitLabel,
                              contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 8),
                            ),
                            onChanged: (raw) {
                              final qty = num.tryParse(raw.trim());
                              if (qty != null) {
                                _materials[index] = (item: material.item, qty: qty);
                              }
                            },
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          visualDensity: VisualDensity.compact,
                          onPressed: () => setState(() => _materials.removeAt(index)),
                        ),
                      ],
                    ),
                  ),
                ),

              _Picker(
                controller: _materialSearch,
                label: context.t('Add a material'),
                results: _materialResults,
                icon: Icons.add,
                onSearch: (query) => _search(query, forMaterial: true),
                onPicked: (item) => setState(() {
                  _materials.add((item: item, qty: 1));
                  _materialSearch.clear();
                  _materialResults = const [];
                }),
              ),

              SectionHeader(context.t('Other costs')),
              TextFormField(
                controller: _labour,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('Labour per batch'),
                  prefixText: symbol,
                  helperText: context.t('Half a batch takes half of this'),
                ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _wastage,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('Wastage'),
                  suffixText: '%',
                  helperText: context.t('Spillage, offcuts, burning — of the materials'),
                ),
              ),

              const SizedBox(height: 18),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Save recipe')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _search(String query, {required bool forMaterial}) async {
    if (query.trim().length < 2) {
      setState(() {
        if (forMaterial) {
          _materialResults = const [];
        } else {
          _finishedResults = const [];
        }
      });
      return;
    }
    try {
      final found = await ref.read(itemRepositoryProvider).search(query);
      if (!mounted) return;
      setState(() {
        // The finished item cannot also be an ingredient in its own recipe, so
        // it is kept out of the material list rather than refused on save.
        if (forMaterial) {
          _materialResults =
              found.where((item) => item.id != _finished?.id).toList();
        } else {
          _finishedResults = found;
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          if (forMaterial) {
            _materialResults = const [];
          } else {
            _finishedResults = const [];
          }
        });
      }
    }
  }

  Future<void> _save() async {
    if (_finished == null) {
      showError(context, context.t('Choose what this recipe makes'));
      return;
    }
    if (_materials.isEmpty) {
      showError(context, context.t('Add at least one material'));
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _saving = true);
    try {
      await ref.read(manufacturingRepositoryProvider).createRecipe({
        'name': _name.text.trim(),
        'item_id': _finished!.id,
        'output_qty': num.parse(_output.text.trim()),
        'labour_cost': num.tryParse(_labour.text.trim()) ?? 0,
        'wastage_percent': num.tryParse(_wastage.text.trim()) ?? 0,
        'components': [
          for (final material in _materials)
            {'item_id': material.item.id, 'qty': material.qty},
        ],
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

class _Picker extends StatelessWidget {
  const _Picker({
    required this.controller,
    required this.label,
    required this.results,
    required this.onSearch,
    required this.onPicked,
    this.icon = Icons.search,
  });

  final TextEditingController controller;
  final String label;
  final List<Item> results;
  final ValueChanged<String> onSearch;
  final ValueChanged<Item> onPicked;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: controller,
          decoration: InputDecoration(labelText: label, prefixIcon: Icon(icon)),
          onChanged: onSearch,
        ),
        if (results.isNotEmpty)
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 150),
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final item in results)
                  ListTile(
                    dense: true,
                    title: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text(item.stockLabel),
                    onTap: () => onPicked(item),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}
