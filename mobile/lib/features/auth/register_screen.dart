import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/utils/validators.dart';
import '../../core/widgets/common.dart';
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
    return PopScope(
      // On step 2 the system back button must return to step 1. Left alone it
      // closes the whole screen and throws away everything already typed.
      canPop: _step == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: context.t('Back'),
            onPressed: _busy
                ? null
                : (_step == 0 ? () => context.goNamed(Routes.login) : _back),
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
                context.t('Create your account'),
                style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 6),
              Text(
                context.t('Step 1 of 2 — your details'),
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 26),
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                textInputAction: TextInputAction.next,
                autovalidateMode: AutovalidateMode.onUserInteraction,
                decoration: InputDecoration(
                  labelText: context.t('Your name'),
                  prefixIcon: const Icon(Icons.person_outline),
                ),
                validator: Validators.minLength(context, 'Your name', 2),
              ),
              const SizedBox(height: 14),

              // Email first, and required. Password reset only works by email —
              // no SMS provider is configured — so an account created with a
              // phone number alone can never be recovered.
              TextFormField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                autocorrect: false,
                autovalidateMode: AutovalidateMode.onUserInteraction,
                decoration: InputDecoration(
                  labelText: context.t('Email address'),
                  helperText: context.t('Used to reset your password if you forget it'),
                  prefixIcon: const Icon(Icons.mail_outline),
                ),
                validator: Validators.email(context),
              ),
              const SizedBox(height: 14),

              TextFormField(
                controller: _phone,
                keyboardType: TextInputType.phone,
                textInputAction: TextInputAction.next,
                autovalidateMode: AutovalidateMode.onUserInteraction,
                decoration: InputDecoration(
                  labelText: context.t('Phone number (optional)'),
                  hintText: '03001234567',
                  prefixIcon: const Icon(Icons.phone_outlined),
                ),
                validator: (value) {
                  final text = (value ?? '').trim();
                  if (text.isEmpty) return null;
                  return RegExp(r'^\+?[\d\s-]{7,20}$').hasMatch(text)
                      ? null
                      : context.t('Enter a valid phone number');
                },
              ),
              const SizedBox(height: 14),

              TextFormField(
                controller: _password,
                obscureText: _obscure,
                textInputAction: TextInputAction.done,
                autofillHints: const [AutofillHints.newPassword],
                autovalidateMode: AutovalidateMode.onUserInteraction,
                decoration: InputDecoration(
                  labelText: context.t('Password'),
                  prefixIcon: const Icon(Icons.lock_outline),
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                    ),
                    tooltip: context.t(_obscure ? 'Show password' : 'Hide password'),
                    onPressed: () => setState(() => _obscure = !_obscure),
                  ),
                ),
                // Shared with the reset screen and matched to the backend rule.
                // The old validator here checked length and a digit but not a
                // letter, so "12345678" passed the form and was then rejected
                // by the server with nothing attached to the field.
                validator: Validators.password(context),
                onChanged: (_) => setState(() {}),
              ),
              PasswordStrengthHint(password: _password.text),
              const SizedBox(height: 26),
              FilledButton(onPressed: _next, child: Text(context.t('Continue'))),
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
                context.t('Set up your shop'),
                style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 6),
              Text(
                context.t('Step 2 of 2 — you can change all of this later'),
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 26),
              TextFormField(
                controller: _businessName,
                textCapitalization: TextCapitalization.words,
                autovalidateMode: AutovalidateMode.onUserInteraction,
                decoration: InputDecoration(
                  labelText: context.t('Shop / business name'),
                  prefixIcon: const Icon(Icons.storefront_outlined),
                ),
                validator: Validators.minLength(context, 'Shop / business name', 2),
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
