import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Picks how an item is measured, and lets the shop add a way nobody thought of.
///
/// This was a list of twelve written into the app — Pcs, Kg, g, L, and so on.
/// It covered a kiryana shop and nothing else. Cloth is sold by the thaan,
/// grain by the maund, timber by the cubic foot, marble by the square foot, and
/// a wholesaler in any of those trades could not enter a single real line.
///
/// No list written here would ever cover every trade, which is the whole point
/// of the last entry: the shop adds its own, and it is theirs from then on.
class UnitField extends ConsumerWidget {
  const UnitField({super.key, required this.value, required this.onChanged});

  /// The short form as stored on the item — "Kg", "Thaan".
  final String value;
  final ValueChanged<String> onChanged;

  static const _addNew = '__add__';

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final created = await showModalBottomSheet<Unit>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _NewUnitSheet(),
    );
    if (created != null) onChanged(created.shortName);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(unitsProvider);
    final units = async.valueOrNull ?? const <Unit>[];

    // The item's own unit may have been renamed or removed since it was saved.
    // Dropping it from the list would silently change the item's unit the next
    // time anybody opened the form and pressed save.
    final shorts = units.map((u) => u.shortName).toList();
    final missing = value.isNotEmpty && !shorts.contains(value);

    return DropdownButtonFormField<String>(
      initialValue: value.isEmpty ? null : value,
      isExpanded: true,
      decoration: InputDecoration(
        labelText: context.t('Unit'),
        // Only while the first load is in flight — after that an empty list is
        // a real answer and the shopkeeper should be adding to it.
        suffixIcon: async.isLoading
            ? const Padding(
                padding: EdgeInsets.all(14),
                child: SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              )
            : null,
      ),
      items: [
        if (missing)
          DropdownMenuItem(value: value, child: Text(value)),
        for (final unit in units)
          DropdownMenuItem(
            value: unit.shortName,
            child: Text(unit.label, overflow: TextOverflow.ellipsis),
          ),
        DropdownMenuItem(
          value: _addNew,
          child: Row(
            children: [
              const Icon(Icons.add, size: 18),
              const SizedBox(width: 8),
              Text(context.t('Add a unit')),
            ],
          ),
        ),
      ],
      onChanged: (picked) {
        if (picked == null) return;
        if (picked == _addNew) {
          _add(context, ref);
          return;
        }
        onChanged(picked);
      },
    );
  }
}

class _NewUnitSheet extends ConsumerStatefulWidget {
  const _NewUnitSheet();

  @override
  ConsumerState<_NewUnitSheet> createState() => _NewUnitSheetState();
}

class _NewUnitSheetState extends ConsumerState<_NewUnitSheet> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _short = TextEditingController();

  bool _allowDecimal = true;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _short.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      final unit = await ref.read(stockRepositoryProvider).createUnit(
            name: _name.text.trim(),
            shortName: _short.text.trim(),
            allowDecimal: _allowDecimal,
          );
      // The dropdown reads from this, so it has to be told.
      ref.invalidate(unitsProvider);
      if (!mounted) return;
      Navigator.pop(context, unit);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.t('Add a unit'), style: theme.textTheme.titleMedium),
            const SizedBox(height: 2),
            Text(
              context.t('However your trade measures things — thaan, maund, '
                  'cubic feet, katta. It stays in your list from now on.'),
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _name,
              autofocus: true,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: context.t('Full name *'),
                hintText: context.t('Cubic Foot'),
              ),
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? 'Required' : null,
              // Filled in as they type, so the short form is one they can
              // accept rather than a second thing to think about.
              onChanged: (text) {
                if (_short.text.isEmpty || text.startsWith(_short.text)) {
                  _short.text = text.length <= 6 ? text : text.substring(0, 6);
                }
              },
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _short,
              decoration: InputDecoration(
                labelText: context.t('Short form *'),
                hintText: context.t('Cft'),
                helperText: context.t('This is what goes on the bill'),
              ),
              maxLength: 16,
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? 'Required' : null,
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text(context.t('Allow half and quarter')),
              subtitle: Text(
                context.t(_allowDecimal
                    ? '2.5 of this can be sold'
                    : 'Only whole numbers — 1, 2, 3'),
              ),
              value: _allowDecimal,
              onChanged: (on) => setState(() => _allowDecimal = on),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _busy ? null : _save,
                child: _busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : Text(context.t('Add')),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
