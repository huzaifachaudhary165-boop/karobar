import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Set up a bill that raises itself on a schedule.
Future<void> showRecurringFormSheet(BuildContext context, WidgetRef ref) async {
  final saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const _RecurringForm(),
  );
  if (saved == true) ref.invalidate(recurringBillsProvider);
}

class _RecurringForm extends ConsumerStatefulWidget {
  const _RecurringForm();

  @override
  ConsumerState<_RecurringForm> createState() => _RecurringFormState();
}

class _RecurringFormState extends ConsumerState<_RecurringForm> {
  final _name = TextEditingController();
  final _partySearch = TextEditingController();
  final _itemSearch = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  final _lines = <({Item item, num qty, num rate})>[];

  Party? _party;
  String _frequency = 'monthly';
  DateTime _startsOn = DateTime.now();
  bool _autoCreate = true;
  bool _saving = false;

  List<Party> _partyResults = const [];
  List<Item> _itemResults = const [];

  static const _frequencies = {
    'weekly': 'Every week',
    'monthly': 'Every month',
    'quarterly': 'Every 3 months',
    'half_yearly': 'Every 6 months',
    'yearly': 'Every year',
  };

  @override
  void dispose() {
    _name.dispose();
    _partySearch.dispose();
    _itemSearch.dispose();
    super.dispose();
  }

  num get _total => _lines.fold<num>(0, (sum, line) => sum + line.qty * line.rate);

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
                context.t('New repeating bill'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),

              TextFormField(
                controller: _name,
                autofocus: true,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: context.t('What is it for'),
                  hintText: context.t('Shop rent, monthly supply'),
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? context.t('Give it a name') : null,
              ),
              const SizedBox(height: 12),

              TextField(
                controller: _partySearch,
                decoration: InputDecoration(
                  labelText: context.t('Customer'),
                  prefixIcon: const Icon(Icons.search),
                ),
                onChanged: _searchParties,
              ),
              if (_partyResults.isNotEmpty)
                ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 140),
                  child: ListView(
                    shrinkWrap: true,
                    children: [
                      for (final party in _partyResults)
                        ListTile(
                          dense: true,
                          title: Text(party.name,
                              maxLines: 1, overflow: TextOverflow.ellipsis),
                          onTap: () {
                            _partySearch.text = party.name;
                            setState(() {
                              _party = party;
                              _partyResults = const [];
                            });
                          },
                        ),
                    ],
                  ),
                ),
              const SizedBox(height: 14),

              DropdownButtonFormField<String>(
                initialValue: _frequency,
                decoration: InputDecoration(labelText: context.t('How often')),
                items: [
                  for (final entry in _frequencies.entries)
                    DropdownMenuItem(value: entry.key, child: Text(context.t(entry.value))),
                ],
                onChanged: (value) => setState(() => _frequency = value ?? 'monthly'),
              ),
              const SizedBox(height: 8),

              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.event_outlined),
                title: Text(context.t('First bill on')),
                subtitle: Text(Fmt.date(_startsOn)),
                trailing: const Icon(Icons.chevron_right),
                onTap: _pickStart,
              ),

              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _autoCreate,
                onChanged: (value) => setState(() => _autoCreate = value),
                title: Text(context.t('Raise it automatically')),
                subtitle: Text(
                  _autoCreate
                      ? context.t('The bill goes out on its own')
                      : context.t('You get a reminder and raise it yourself'),
                ),
              ),
              const SizedBox(height: 8),

              SectionHeader(context.t('What is on the bill')),
              for (final (index, line) in _lines.indexed)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: AppCard(
                    padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${line.item.name}  ×${trimZeros(line.qty)}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodyMedium,
                          ),
                        ),
                        Text(
                          Fmt.money(line.qty * line.rate, symbol: symbol, decimals: false),
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          visualDensity: VisualDensity.compact,
                          onPressed: () => setState(() => _lines.removeAt(index)),
                        ),
                      ],
                    ),
                  ),
                ),

              TextField(
                controller: _itemSearch,
                decoration: InputDecoration(
                  labelText: context.t('Add an item'),
                  prefixIcon: const Icon(Icons.add),
                ),
                onChanged: _searchItems,
              ),
              if (_itemResults.isNotEmpty)
                ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 140),
                  child: ListView(
                    shrinkWrap: true,
                    children: [
                      for (final item in _itemResults)
                        ListTile(
                          dense: true,
                          title: Text(item.name,
                              maxLines: 1, overflow: TextOverflow.ellipsis),
                          subtitle:
                              Text(Fmt.money(item.salePrice, symbol: symbol, decimals: false)),
                          onTap: () {
                            setState(() {
                              _lines.add((item: item, qty: 1, rate: item.salePrice));
                              _itemResults = const [];
                              _itemSearch.clear();
                            });
                          },
                        ),
                    ],
                  ),
                ),

              if (_lines.isNotEmpty) ...[
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: Text(context.t('Each time'), style: theme.textTheme.bodyMedium),
                    ),
                    Text(
                      Fmt.money(_total, symbol: symbol),
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                  ],
                ),
              ],

              const SizedBox(height: 16),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Start this schedule')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _searchParties(String query) async {
    if (query.trim().length < 2) {
      setState(() => _partyResults = const []);
      return;
    }
    try {
      final found = await ref.read(partyRepositoryProvider).search(query);
      if (mounted) setState(() => _partyResults = found);
    } catch (_) {
      if (mounted) setState(() => _partyResults = const []);
    }
  }

  Future<void> _searchItems(String query) async {
    if (query.trim().length < 2) {
      setState(() => _itemResults = const []);
      return;
    }
    try {
      final found = await ref.read(itemRepositoryProvider).search(query);
      if (mounted) setState(() => _itemResults = found);
    } catch (_) {
      if (mounted) setState(() => _itemResults = const []);
    }
  }

  Future<void> _pickStart() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _startsOn,
      // Backdating is allowed on purpose: a shop setting up a schedule that
      // started three months ago gets those three bills raised.
      firstDate: DateTime.now().subtract(const Duration(days: 365)),
      lastDate: DateTime.now().add(const Duration(days: 730)),
    );
    if (picked != null) setState(() => _startsOn = picked);
  }

  Future<void> _save() async {
    if (_lines.isEmpty) {
      showError(context, context.t('Add at least one item to the bill'));
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _saving = true);
    try {
      await ref.read(recurringRepositoryProvider).create({
        'name': _name.text.trim(),
        if (_party != null) 'party_id': _party!.id,
        'frequency': _frequency,
        'starts_on': Fmt.iso(_startsOn),
        'auto_create': _autoCreate,
        'lines': [
          for (final line in _lines)
            {
              'item_id': line.item.id,
              'item_name': line.item.name,
              'qty': line.qty,
              'rate': line.rate,
              'tax_rate': line.item.taxRate,
            },
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
