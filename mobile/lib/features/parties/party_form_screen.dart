import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../data/offline_write.dart';
import '../../providers.dart';

/// Create or edit a customer / supplier.
class PartyFormScreen extends ConsumerStatefulWidget {
  const PartyFormScreen({super.key, this.partyId, this.initialType = 'customer'});

  final String? partyId;
  final String initialType;

  @override
  ConsumerState<PartyFormScreen> createState() => _PartyFormScreenState();
}

class _PartyFormScreenState extends ConsumerState<PartyFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _address = TextEditingController();
  final _openingBalance = TextEditingController();
  final _creditLimit = TextEditingController();

  late String _type = widget.initialType;
  bool _busy = false;
  bool _loading = false;

  bool get _isEditing => widget.partyId != null;

  @override
  void initState() {
    super.initState();
    if (_isEditing) _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _email.dispose();
    _address.dispose();
    _openingBalance.dispose();
    _creditLimit.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final party = await ref.read(partyRepositoryProvider).get(widget.partyId!);
      _name.text = party.name;
      _phone.text = party.phone ?? '';
      _email.text = party.email ?? '';
      _address.text = party.billingAddress ?? '';
      _creditLimit.text = party.creditLimit?.toString() ?? '';
      setState(() => _type = party.partyType);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);

    final body = <String, dynamic>{
      'name': _name.text.trim(),
      'party_type': _type,
      if (_phone.text.trim().isNotEmpty) 'phone': _phone.text.trim(),
      if (_email.text.trim().isNotEmpty) 'email': _email.text.trim(),
      if (_address.text.trim().isNotEmpty) 'billing_address': _address.text.trim(),
      if (_creditLimit.text.trim().isNotEmpty)
        'credit_limit': num.tryParse(_creditLimit.text.trim()),
      if (!_isEditing && _openingBalance.text.trim().isNotEmpty)
        'opening_balance': num.tryParse(_openingBalance.text.trim()) ?? 0,
    };

    try {
      final repository = ref.read(partyRepositoryProvider);
      final result = await saveOrQueue<void>(
        ref,
        entity: 'party',
        data: body,
        operation: _isEditing ? 'update' : 'create',
        serverId: widget.partyId,
        send: () => _isEditing
            ? repository.update(widget.partyId!, body)
            : repository.create(body),
      );
      if (!mounted) return;
      invalidateBusinessData(ref);
      showSuccess(
        context,
        result.queued
            ? queuedMessage
            : (_isEditing ? 'Party updated.' : '${_name.text.trim()} added.'),
      );
      context.pop();
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isEditing ? 'Edit party' : 'New party'),
        actions: [
          TextButton(
            onPressed: _busy ? null : _save,
            child: Text(context.tr('save')),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  SegmentedButton<String>(
                    segments: [
                      ButtonSegment(
                        value: 'customer',
                        label: Text(context.t('Customer')),
                        icon: const Icon(Icons.person_outline),
                      ),
                      ButtonSegment(
                        value: 'supplier',
                        label: Text(context.t('Supplier')),
                        icon: const Icon(Icons.local_shipping_outlined),
                      ),
                    ],
                    selected: {_type == 'both' ? 'customer' : _type},
                    onSelectionChanged: (values) =>
                        setState(() => _type = values.first),
                  ),
                  const SizedBox(height: 18),
                  TextFormField(
                    controller: _name,
                    textCapitalization: TextCapitalization.words,
                    autofocus: !_isEditing,
                    decoration: InputDecoration(
                      labelText: context.t('Name *'),
                      prefixIcon: const Icon(Icons.badge_outlined),
                    ),
                    validator: (value) =>
                        (value == null || value.trim().isEmpty) ? 'Name is required' : null,
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    decoration: InputDecoration(
                      labelText: context.t('Phone'),
                      helperText: 'Used for WhatsApp reminders and invoice sharing',
                      prefixIcon: const Icon(Icons.phone_outlined),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    decoration: InputDecoration(
                      labelText: context.t('Email'),
                      prefixIcon: const Icon(Icons.mail_outline),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: _address,
                    maxLines: 2,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: InputDecoration(
                      labelText: context.t('Address'),
                      prefixIcon: const Icon(Icons.location_on_outlined),
                    ),
                  ),
                  if (!_isEditing) ...[
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _openingBalance,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        labelText: context.t('Opening balance'),
                        helperText: 'Existing dues. Positive means they owe you.',
                        prefixIcon: const Icon(Icons.account_balance_outlined),
                      ),
                    ),
                  ],
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: _creditLimit,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(
                      labelText: context.t('Credit limit'),
                      helperText: 'You will be warned when their dues cross this',
                      prefixIcon: const Icon(Icons.credit_score_outlined),
                    ),
                  ),
                  const SizedBox(height: 26),
                  FilledButton(
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
                        : Text(_isEditing ? 'Save changes' : 'Add party'),
                  ),
                ],
              ),
            ),
    );
  }
}
