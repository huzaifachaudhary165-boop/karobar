import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../providers.dart';

/// Shop profile plus the settings that change how bills behave.
///
/// Each toggle saves immediately — a shopkeeper changing one switch shouldn't
/// have to find a save button.
class BusinessSettingsScreen extends ConsumerStatefulWidget {
  const BusinessSettingsScreen({super.key});

  @override
  ConsumerState<BusinessSettingsScreen> createState() => _BusinessSettingsScreenState();
}

class _BusinessSettingsScreenState extends ConsumerState<BusinessSettingsScreen> {
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _address = TextEditingController();
  final _taxNumber = TextEditingController();
  final _terms = TextEditingController();
  final _invoicePrefix = TextEditingController();
  final _dueDays = TextEditingController();

  Map<String, dynamic> _settings = const {};

  /// India files GST, Pakistan files NTN — the same box writes to whichever
  /// column this shop's tax regime uses.
  String _taxField = 'ntn';
  String _taxLabel = 'NTN';

  bool _loading = true;
  bool _savingProfile = false;
  bool _dirty = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final controller in [
      _name, _phone, _email, _address, _taxNumber, _terms, _invoicePrefix, _dueDays,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final repository = ref.read(businessRepositoryProvider);
      final business = await repository.current();
      final settings = await repository.settings();

      _name.text = business['name']?.toString() ?? '';
      _phone.text = business['phone']?.toString() ?? '';
      _email.text = business['email']?.toString() ?? '';
      _address.text = business['address_line1']?.toString() ?? '';
      final usesGst = business['gstin'] != null ||
          business['tax_type']?.toString() == 'gst' ||
          business['country']?.toString().toLowerCase() == 'india';
      _taxField = usesGst ? 'gstin' : 'ntn';
      _taxLabel = usesGst ? 'GSTIN' : 'NTN';
      _taxNumber.text = business[_taxField]?.toString() ?? '';
      _terms.text = settings['terms_and_conditions']?.toString() ?? '';
      _invoicePrefix.text = settings['invoice_prefix']?.toString() ?? '';
      _dueDays.text = settings['default_due_days']?.toString() ?? '';

      if (mounted) setState(() => _settings = settings);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _saveProfile() async {
    setState(() => _savingProfile = true);
    try {
      final repository = ref.read(businessRepositoryProvider);
      await repository.update({
        'name': _name.text.trim(),
        'phone': _phone.text.trim().isEmpty ? null : _phone.text.trim(),
        'email': _email.text.trim().isEmpty ? null : _email.text.trim(),
        'address_line1': _address.text.trim().isEmpty ? null : _address.text.trim(),
        if (_taxNumber.text.trim().isNotEmpty) _taxField: _taxNumber.text.trim(),
      });
      await repository.updateSettings({
        'terms_and_conditions':
            _terms.text.trim().isEmpty ? null : _terms.text.trim(),
        if (_invoicePrefix.text.trim().isNotEmpty)
          'invoice_prefix': _invoicePrefix.text.trim(),
        if (int.tryParse(_dueDays.text.trim()) != null)
          'default_due_days': int.parse(_dueDays.text.trim()),
      });

      if (!mounted) return;
      setState(() => _dirty = false);
      ref.invalidate(businessProfileProvider);
      ref.invalidate(businessSettingsProvider);
      showSuccess(context, 'Shop details saved.');
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _savingProfile = false);
    }
  }

  Future<void> _toggle(String key, bool value) async {
    // Optimistic: flip locally, roll back if the server rejects it.
    final previous = _settings[key];
    setState(() => _settings = {..._settings, key: value});

    try {
      await ref.read(businessRepositoryProvider).updateSettings({key: value});
      if (mounted) ref.invalidate(businessSettingsProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() => _settings = {..._settings, key: previous});
      showError(context, error);
    }
  }

  bool _flag(String key, {bool fallback = false}) =>
      _settings[key] as bool? ?? fallback;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Shop settings'),
        actions: [
          if (_dirty)
            TextButton(
              onPressed: _savingProfile ? null : _saveProfile,
              child: Text(context.t('Save')),
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.only(bottom: 40),
              children: [
                const SectionHeader('Shop details'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: AppCard(
                    child: Column(
                      children: [
                        _field(_name, 'Shop name', Icons.storefront_outlined),
                        const SizedBox(height: 12),
                        _field(_phone, 'Phone', Icons.phone_outlined,
                            keyboard: TextInputType.phone),
                        const SizedBox(height: 12),
                        _field(_email, 'Email', Icons.mail_outline,
                            keyboard: TextInputType.emailAddress),
                        const SizedBox(height: 12),
                        _field(_address, 'Address', Icons.location_on_outlined, lines: 2),
                        const SizedBox(height: 12),
                        _field(_taxNumber, _taxLabel, Icons.badge_outlined),
                      ],
                    ),
                  ),
                ),

                const SectionHeader('Billing'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: AppCard(
                    child: Column(
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: _field(
                                _invoicePrefix,
                                'Invoice prefix',
                                Icons.tag_outlined,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _field(
                                _dueDays,
                                'Due after (days)',
                                Icons.event_outlined,
                                keyboard: TextInputType.number,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        _field(_terms, 'Terms printed on bills', Icons.gavel_outlined,
                            lines: 3),
                      ],
                    ),
                  ),
                ),

                const SectionHeader('How bills behave'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: AppCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        _switch(
                          'allow_negative_stock',
                          'Allow selling below stock',
                          'For shops that sell ahead of a delivery being booked in',
                          Icons.inventory_2_outlined,
                        ),
                        const Divider(height: 1),
                        _switch(
                          'prices_include_tax',
                          'Prices include tax',
                          'Item prices already have tax built in',
                          Icons.percent,
                        ),
                        const Divider(height: 1),
                        _switch(
                          'auto_round_off',
                          'Round off invoice totals',
                          'Rounds the final amount to the nearest whole number',
                          Icons.filter_tilt_shift,
                          fallback: true,
                        ),
                        const Divider(height: 1),
                        _switch(
                          'show_amount_in_words',
                          'Print amount in words',
                          'Adds “Rupees Four Thousand Only” under the total',
                          Icons.abc,
                          fallback: true,
                        ),
                      ],
                    ),
                  ),
                ),

                const SectionHeader('Reminders'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: AppCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        _switch(
                          'payment_reminder_enabled',
                          'Payment reminders',
                          'Alert you when a customer’s bill goes overdue',
                          Icons.schedule,
                          fallback: true,
                        ),
                        const Divider(height: 1),
                        _switch(
                          'low_stock_alerts',
                          'Low-stock alerts',
                          'Warn you before an item runs out',
                          Icons.warning_amber_rounded,
                          fallback: true,
                        ),
                      ],
                    ),
                  ),
                ),

                const SectionHeader('Assistant'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: AppCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        _switch(
                          'ai_enabled',
                          'AI assistant',
                          'Chat, voice and bill scanning',
                          Icons.auto_awesome,
                          fallback: true,
                        ),
                        const Divider(height: 1),
                        _switch(
                          'ai_auto_confirm',
                          'Let the assistant save without asking',
                          'Off means it describes the change and waits for you',
                          Icons.verified_outlined,
                        ),
                      ],
                    ),
                  ),
                ),

                const SizedBox(height: 24),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: FilledButton(
                    onPressed: _savingProfile ? null : _saveProfile,
                    child: _savingProfile
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Text('Save shop details'),
                  ),
                ),
                const SizedBox(height: 10),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Text(
                    'Switches above save on their own.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _field(
    TextEditingController controller,
    String label,
    IconData icon, {
    int lines = 1,
    TextInputType? keyboard,
  }) {
    return TextField(
      controller: controller,
      maxLines: lines,
      keyboardType: keyboard,
      onChanged: (_) {
        if (!_dirty) setState(() => _dirty = true);
      },
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        isDense: true,
      ),
    );
  }

  Widget _switch(
    String key,
    String title,
    String subtitle,
    IconData icon, {
    bool fallback = false,
  }) {
    return SwitchListTile(
      value: _flag(key, fallback: fallback),
      onChanged: (value) => _toggle(key, value),
      secondary: Icon(icon, size: 21, color: AppColors.primary),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
      subtitle: Text(subtitle, style: const TextStyle(fontSize: 11.5)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
    );
  }
}
