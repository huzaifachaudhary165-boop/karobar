import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/google_button.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';

/// Two steps: who you are, then what your shop is. Both are needed before the
/// app has anything to show, so they live in one flow rather than an onboarding
/// wizard the user can skip.
class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _pageController = PageController();
  final _step1Key = GlobalKey<FormState>();
  final _step2Key = GlobalKey<FormState>();

  final _name = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _businessName = TextEditingController();

  String _businessType = 'retail';
  String _country = 'Pakistan';
  bool _busy = false;
  bool _obscure = true;
  int _step = 0;

  static const _businessTypes = {
    'retail': 'Retail shop',
    'wholesale': 'Wholesale',
    'distributor': 'Distributor',
    'manufacturing': 'Manufacturing',
    'service': 'Services',
    'pharmacy': 'Pharmacy',
    'restaurant': 'Restaurant',
    'other': 'Other',
  };

  @override
  void dispose() {
    _pageController.dispose();
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _password.dispose();
    _businessName.dispose();
    super.dispose();
  }

  void _next() {
    if (!_step1Key.currentState!.validate()) return;
    setState(() => _step = 1);
    _pageController.nextPage(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
    );
  }

  void _back() {
    setState(() => _step = 0);
    _pageController.previousPage(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
    );
  }

  Future<void> _submit() async {
    if (!_step2Key.currentState!.validate()) return;
    setState(() => _busy = true);

    try {
      await ref.read(sessionProvider.notifier).register(
            name: _name.text.trim(),
            password: _password.text,
            email: _email.text.trim().isEmpty ? null : _email.text.trim(),
            phone: _phone.text.trim().isEmpty ? null : _phone.text.trim(),
            businessName: _businessName.text.trim(),
            businessType: _businessType,
            country: _country,
          );
      if (mounted) context.goNamed(Routes.home);
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
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: _step == 0 ? () => context.goNamed(Routes.login) : _back,
        ),
        title: const KarobarLogo(size: LogoSize.small, showSubtitle: false),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(3),
          child: LinearProgressIndicator(
            value: _step == 0 ? 0.5 : 1,
            minHeight: 3,
            backgroundColor: Theme.of(context).colorScheme.outlineVariant,
          ),
        ),
      ),
      body: SafeArea(
        child: PageView(
          controller: _pageController,
          physics: const NeverScrollableScrollPhysics(),
          children: [_accountStep(), _businessStep()],
        ),
      ),
    );
  }

  Widget _accountStep() {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Form(
          key: _step1Key,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Create your account',
                style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 6),
              Text(
                'Step 1 of 2 — your details',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 26),
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                textInputAction: TextInputAction.next,
                decoration: const InputDecoration(
                  labelText: 'Your name',
                  prefixIcon: Icon(Icons.person_outline),
                ),
                validator: (value) => (value == null || value.trim().length < 2)
                    ? 'Enter your name'
                    : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _phone,
                keyboardType: TextInputType.phone,
                textInputAction: TextInputAction.next,
                decoration: InputDecoration(
                  labelText: context.t('Phone number'),
                  hintText: '03001234567',
                  prefixIcon: const Icon(Icons.phone_outlined),
                ),
                validator: (value) {
                  if ((value == null || value.trim().isEmpty) &&
                      _email.text.trim().isEmpty) {
                    return 'Enter a phone number or an email address';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                decoration: InputDecoration(
                  labelText: context.t('Email (optional)'),
                  prefixIcon: const Icon(Icons.mail_outline),
                ),
                validator: (value) {
                  if (value == null || value.trim().isEmpty) return null;
                  return value.contains('@') ? null : 'Enter a valid email address';
                },
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _password,
                obscureText: _obscure,
                textInputAction: TextInputAction.done,
                decoration: InputDecoration(
                  labelText: context.t('Password'),
                  helperText: 'At least 8 characters, with a number',
                  prefixIcon: const Icon(Icons.lock_outline),
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                    ),
                    onPressed: () => setState(() => _obscure = !_obscure),
                  ),
                ),
                validator: (value) {
                  if (value == null || value.length < 8) return 'At least 8 characters';
                  if (!value.contains(RegExp(r'\d'))) return 'Include at least one number';
                  return null;
                },
              ),
              const SizedBox(height: 26),
              FilledButton(onPressed: _next, child: Text(context.t('Continue'))),
              // Google signs the user straight in and creates their shop, so it
              // sits on the first step rather than after the shop-details step.
              const GoogleButton(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _businessStep() {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Form(
          key: _step2Key,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Set up your shop',
                style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 6),
              Text(
                'Step 2 of 2 — you can change all of this later',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 26),
              TextFormField(
                controller: _businessName,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(
                  labelText: 'Shop / business name',
                  prefixIcon: Icon(Icons.storefront_outlined),
                ),
                validator: (value) => (value == null || value.trim().length < 2)
                    ? 'Enter your business name'
                    : null,
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<String>(
                initialValue: _businessType,
                decoration: InputDecoration(
                  labelText: context.t('Business type'),
                  prefixIcon: const Icon(Icons.category_outlined),
                ),
                items: _businessTypes.entries
                    .map((entry) =>
                        DropdownMenuItem(value: entry.key, child: Text(entry.value)))
                    .toList(),
                onChanged: (value) => setState(() => _businessType = value ?? 'retail'),
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<String>(
                initialValue: _country,
                decoration: InputDecoration(
                  labelText: context.t('Country'),
                  prefixIcon: const Icon(Icons.public_outlined),
                ),
                items: const [
                  DropdownMenuItem(value: 'Pakistan', child: Text('Pakistan (PKR)')),
                  DropdownMenuItem(value: 'India', child: Text('India (INR)')),
                  DropdownMenuItem(value: 'Bangladesh', child: Text('Bangladesh (BDT)')),
                  DropdownMenuItem(
                    value: 'United Arab Emirates',
                    child: Text('UAE (AED)'),
                  ),
                ],
                onChanged: (value) => setState(() => _country = value ?? 'Pakistan'),
              ),
              const SizedBox(height: 22),
              AppCard(
                child: Row(
                  children: [
                    const Icon(Icons.auto_awesome_outlined, size: 20),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Your shop starts with common units, tax rates and expense '
                        'categories already set up.',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : Text(context.t('Create my shop')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
