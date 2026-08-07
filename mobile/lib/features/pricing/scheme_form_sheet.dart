import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Create an offer that comes off the bill on its own.
///
/// Deliberately few fields. Every extra condition is one more way for a
/// shopkeeper to be unable to explain a total to the customer in front of
/// them, and a discount nobody can explain is worse than no discount.
Future<void> showSchemeFormSheet(BuildContext context, WidgetRef ref) async {
  final saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const _SchemeForm(),
  );
  if (saved == true) ref.invalidate(schemesProvider);
}

class _SchemeForm extends ConsumerStatefulWidget {
  const _SchemeForm();

  @override
  ConsumerState<_SchemeForm> createState() => _SchemeFormState();
}

class _SchemeFormState extends ConsumerState<_SchemeForm> {
  final _name = TextEditingController();
  final _value = TextEditingController();
  final _minAmount = TextEditingController();
  final _search = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  String _scope = 'bill';
  bool _isPercent = true;
  DateTime? _endsOn;
  Item? _item;
  List<Item> _results = const [];
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _value.dispose();
    _minAmount.dispose();
    _search.dispose();
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
                context.t('New offer'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),

              TextFormField(
                controller: _name,
                autofocus: true,
                textCapitalization: TextCapitalization.words,
                decoration: InputDecoration(
                  labelText: context.t('What to call it'),
                  hintText: context.t('Eid offer, Clearance'),
                  helperText: context.t('This appears on the bill'),
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? context.t('Give it a name') : null,
              ),
              const SizedBox(height: 14),

              SegmentedButton<String>(
                segments: [
                  ButtonSegment(value: 'bill', label: Text(context.t('Whole bill'))),
                  ButtonSegment(value: 'item', label: Text(context.t('One item'))),
                ],
                selected: {_scope},
                onSelectionChanged: (values) => setState(() {
                  _scope = values.first;
                  if (_scope == 'bill') _item = null;
                }),
              ),

              if (_scope == 'item') ...[
                const SizedBox(height: 12),
                TextField(
                  controller: _search,
                  decoration: InputDecoration(
                    labelText: context.t('Which item'),
                    prefixIcon: const Icon(Icons.search),
                  ),
                  onChanged: _searchItems,
                ),
                if (_results.isNotEmpty)
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 150),
                    child: ListView(
                      shrinkWrap: true,
                      children: [
                        for (final item in _results)
                          ListTile(
                            dense: true,
                            title: Text(item.name,
                                maxLines: 1, overflow: TextOverflow.ellipsis),
                            onTap: () {
                              _search.text = item.name;
                              setState(() {
                                _item = item;
                                _results = const [];
                              });
                            },
                          ),
                      ],
                    ),
                  ),
              ],

              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _value,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        labelText: context.t('Take off'),
                        suffixText: _isPercent ? '%' : symbol.trim(),
                      ),
                      validator: (value) {
                        final amount = num.tryParse((value ?? '').trim());
                        if (amount == null || amount <= 0) {
                          return context.t('How much comes off');
                        }
                        if (_isPercent && amount > 100) return context.t('At most 100%');
                        return null;
                      },
                    ),
                  ),
                  const SizedBox(width: 10),
                  SegmentedButton<bool>(
                    showSelectedIcon: false,
                    segments: [
                      ButtonSegment(value: true, label: Text(context.t('%'))),
                      ButtonSegment(value: false, label: Text(symbol.trim())),
                    ],
                    selected: {_isPercent},
                    onSelectionChanged: (values) =>
                        setState(() => _isPercent = values.first),
                  ),
                ],
              ),

              const SizedBox(height: 12),
              TextFormField(
                controller: _minAmount,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('Only on bills over'),
                  prefixText: symbol,
                  helperText: context.t('Leave empty for every bill'),
                ),
              ),

              const SizedBox(height: 8),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.event_outlined),
                title: Text(context.t('Runs until')),
                subtitle: Text(
                  _endsOn == null ? context.t('No end date') : Fmt.date(_endsOn),
                ),
                trailing: _endsOn == null
                    ? const Icon(Icons.chevron_right)
                    : IconButton(
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () => setState(() => _endsOn = null),
                      ),
                onTap: _pickEnd,
              ),

              const SizedBox(height: 8),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Start this offer')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _searchItems(String query) async {
    if (query.trim().length < 2) {
      setState(() => _results = const []);
      return;
    }
    try {
      final found = await ref.read(itemRepositoryProvider).search(query);
      if (mounted) setState(() => _results = found);
    } catch (_) {
      if (mounted) setState(() => _results = const []);
    }
  }

  Future<void> _pickEnd() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _endsOn ?? DateTime.now().add(const Duration(days: 30)),
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 3650)),
    );
    if (picked != null) setState(() => _endsOn = picked);
  }

  Future<void> _save() async {
    if (_scope == 'item' && _item == null) {
      showError(context, context.t('Choose the item this offer is on'));
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _saving = true);
    try {
      await ref.read(pricingRepositoryProvider).createScheme({
        'name': _name.text.trim(),
        'scope': _scope,
        if (_item != null) 'item_id': _item!.id,
        'discount_type': _isPercent ? 'percent' : 'amount',
        'discount_value': num.parse(_value.text.trim()),
        if (num.tryParse(_minAmount.text.trim()) != null)
          'min_amount': num.parse(_minAmount.text.trim()),
        if (_endsOn != null) 'ends_on': Fmt.iso(_endsOn!),
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
