import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/utils/loan_preview.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Record a loan, with the instalment worked out as it is typed.
///
/// The live figure matters more than it looks: a shopkeeper comparing two
/// offers can see immediately that "12% flat" costs more than "12%", which is
/// the single most expensive misunderstanding in small-business borrowing.
Future<void> showLoanFormSheet(BuildContext context, WidgetRef ref) async {
  final saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const _LoanForm(),
  );
  if (saved == true) {
    ref.invalidate(loansProvider);
    ref.invalidate(loanSummaryProvider);
    ref.invalidate(bankAccountsProvider);
  }
}

class _LoanForm extends ConsumerStatefulWidget {
  const _LoanForm();

  @override
  ConsumerState<_LoanForm> createState() => _LoanFormState();
}

class _LoanFormState extends ConsumerState<_LoanForm> {
  final _lender = TextEditingController();
  final _principal = TextEditingController();
  final _rate = TextEditingController();
  final _tenure = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  String _type = 'bank';
  String _interestType = 'reducing';
  String? _accountId;
  DateTime _start = DateTime.now();
  bool _saving = false;

  static const _types = {
    'bank': 'Bank loan',
    'personal': 'From a person',
    'vehicle': 'Vehicle',
    'gold': 'Gold',
    'business': 'Business',
    'other': 'Other',
  };

  @override
  void initState() {
    super.initState();
    for (final controller in [_principal, _rate, _tenure]) {
      controller.addListener(() => setState(() {}));
    }
  }

  @override
  void dispose() {
    _lender.dispose();
    _principal.dispose();
    _rate.dispose();
    _tenure.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;
    final accounts = ref.watch(bankAccountsProvider).valueOrNull ?? const <BankAccount>[];
    final instalment = _previewInstalment();
    final totalInterest = _previewTotalInterest();

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
                context.t('New loan'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),

              TextFormField(
                controller: _lender,
                textCapitalization: TextCapitalization.words,
                decoration: InputDecoration(
                  labelText: context.t('Who lent it'),
                  hintText: context.t('Meezan Bank, Chacha Rashid'),
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? context.t('Name the lender') : null,
              ),
              const SizedBox(height: 12),

              DropdownButtonFormField<String>(
                initialValue: _type,
                decoration: InputDecoration(labelText: context.t('Kind of loan')),
                items: [
                  for (final entry in _types.entries)
                    DropdownMenuItem(value: entry.key, child: Text(context.t(entry.value))),
                ],
                onChanged: (value) => setState(() {
                  _type = value ?? 'bank';
                  // Borrowing from family is normally interest-free; start there
                  // rather than making them clear a rate they never agreed to.
                  if (_type == 'personal' && _rate.text.trim().isEmpty) {
                    _interestType = 'none';
                  }
                }),
              ),
              const SizedBox(height: 12),

              TextFormField(
                controller: _principal,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(labelText: context.t('Amount borrowed')),
                validator: (value) {
                  final amount = num.tryParse((value ?? '').trim());
                  return amount == null || amount <= 0
                      ? context.t('Enter how much was borrowed')
                      : null;
                },
              ),
              const SizedBox(height: 12),

              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _rate,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        labelText: context.t('Interest'),
                        suffixText: '% / year',
                        hintText: '0',
                      ),
                      validator: (value) {
                        final raw = (value ?? '').trim();
                        if (raw.isEmpty) return null;
                        final rate = num.tryParse(raw);
                        if (rate == null || rate < 0 || rate > 100) {
                          return context.t('0 to 100');
                        }
                        return null;
                      },
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _tenure,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(
                        labelText: context.t('Term'),
                        suffixText: context.t('months'),
                      ),
                      validator: (value) {
                        final months = int.tryParse((value ?? '').trim());
                        return months == null || months <= 0
                            ? context.t('How many months')
                            : null;
                      },
                    ),
                  ),
                ],
              ),

              if ((num.tryParse(_rate.text.trim()) ?? 0) > 0) ...[
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  segments: [
                    ButtonSegment(
                      value: 'reducing',
                      label: Text(context.t('Reducing')),
                    ),
                    ButtonSegment(value: 'flat', label: Text(context.t('Flat'))),
                  ],
                  selected: {_interestType},
                  onSelectionChanged: (values) =>
                      setState(() => _interestType = values.first),
                ),
                Padding(
                  padding: const EdgeInsets.only(top: 6, left: 4),
                  child: Text(
                    _interestType == 'flat'
                        ? context.t('Charged on the full amount for the whole term')
                        : context.t('Charged on what is still owed, so it falls each month'),
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ),
              ],

              if (instalment != null) ...[
                const SizedBox(height: 14),
                AppCard(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.event_repeat, size: 18),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              context.t('Monthly instalment'),
                              style: theme.textTheme.bodyMedium,
                            ),
                          ),
                          Text(
                            Fmt.money(instalment, symbol: symbol),
                            style: theme.textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w800),
                          ),
                        ],
                      ),
                      // What the borrowing actually costs. It is the number a
                      // lender leads with least and a shopkeeper needs most.
                      if ((totalInterest ?? 0) > 0) ...[
                        const Divider(height: 20),
                        Row(
                          children: [
                            const SizedBox(width: 28),
                            Expanded(
                              child: Text(
                                context.t('Interest over the whole term'),
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ),
                            Text(
                              Fmt.money(totalInterest, symbol: symbol, decimals: false),
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
              ],

              const SizedBox(height: 12),
              if (accounts.isNotEmpty)
                DropdownButtonFormField<String>(
                  initialValue: _accountId,
                  decoration: InputDecoration(
                    labelText: context.t('Money received into'),
                    helperText: context.t('Leave empty if it did not go through an account'),
                  ),
                  items: [
                    for (final account in accounts)
                      DropdownMenuItem(value: account.id, child: Text(account.name)),
                  ],
                  onChanged: (value) => setState(() => _accountId = value),
                ),
              const SizedBox(height: 12),

              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.calendar_today_outlined),
                title: Text(context.t('Taken on')),
                subtitle: Text(Fmt.date(_start)),
                trailing: const Icon(Icons.chevron_right),
                onTap: _pickDate,
              ),
              const SizedBox(height: 8),

              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Save loan')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  num? _previewInstalment() => previewInstalment(
        principal: num.tryParse(_principal.text.trim()),
        months: int.tryParse(_tenure.text.trim()),
        rate: num.tryParse(_rate.text.trim()) ?? 0,
        interestType: _interestType,
      );

  num? _previewTotalInterest() => previewTotalInterest(
        principal: num.tryParse(_principal.text.trim()),
        months: int.tryParse(_tenure.text.trim()),
        rate: num.tryParse(_rate.text.trim()) ?? 0,
        interestType: _interestType,
      );

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _start,
      firstDate: DateTime(2000),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked != null) setState(() => _start = picked);
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);

    final rate = num.tryParse(_rate.text.trim()) ?? 0;
    try {
      await ref.read(financeRepositoryProvider).createLoan({
        'lender_name': _lender.text.trim(),
        'loan_type': _type,
        'principal': num.parse(_principal.text.trim()),
        'interest_rate': rate,
        'interest_type': rate <= 0 ? 'none' : _interestType,
        'tenure_months': int.parse(_tenure.text.trim()),
        'start_date': Fmt.iso(_start),
        if (_accountId != null) 'account_id': _accountId,
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
