import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/google_button.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';

/// Two ways in: password, or a one-time code sent to a phone/email.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _identifier = TextEditingController();
  final _password = TextEditingController();
  final _otp = TextEditingController();

  bool _useOtp = false;
  bool _otpSent = false;
  bool _busy = false;
  bool _obscure = true;
  String? _debugOtp;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    _otp.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);

    try {
      final session = ref.read(sessionProvider.notifier);
      if (_useOtp) {
        if (!_otpSent) {
          final code = await session.sendOtp(_identifier.text.trim());
          if (!mounted) return;
          setState(() {
            _otpSent = true;
            _debugOtp = code;
          });
          showSuccess(context, 'Code sent to ${_identifier.text.trim()}');
          return;
        }
        await session.verifyOtp(_identifier.text.trim(), _otp.text.trim());
      } else {
        await session.login(_identifier.text.trim(), _password.text);
      }
      if (mounted) context.goNamed(Routes.home);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const SizedBox(height: 12),
                    const Center(
                      child: KarobarLogo(size: LogoSize.large, direction: Axis.vertical),
                    ),
                    const SizedBox(height: 28),
                    Text(
                      'Welcome back',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Sign in to your shop',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                    const SizedBox(height: 28),

                    TextFormField(
                      controller: _identifier,
                      enabled: !_otpSent,
                      keyboardType: TextInputType.emailAddress,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [AutofillHints.username],
                      decoration: InputDecoration(
                        labelText: context.t('Email or phone number'),
                        prefixIcon: const Icon(Icons.person_outline),
                      ),
                      validator: (value) => (value == null || value.trim().length < 3)
                          ? 'Enter your email or phone number'
                          : null,
                    ),
                    const SizedBox(height: 14),

                    if (!_useOtp)
                      TextFormField(
                        controller: _password,
                        obscureText: _obscure,
                        textInputAction: TextInputAction.done,
                        autofillHints: const [AutofillHints.password],
                        onFieldSubmitted: (_) => _submit(),
                        decoration: InputDecoration(
                          labelText: context.t('Password'),
                          prefixIcon: const Icon(Icons.lock_outline),
                          suffixIcon: IconButton(
                            icon: Icon(
                              _obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                            ),
                            onPressed: () => setState(() => _obscure = !_obscure),
                          ),
                        ),
                        validator: (value) => (value == null || value.isEmpty)
                            ? 'Enter your password'
                            : null,
                      )
                    else if (_otpSent)
                      TextFormField(
                        controller: _otp,
                        keyboardType: TextInputType.number,
                        textInputAction: TextInputAction.done,
                        autofillHints: const [AutofillHints.oneTimeCode],
                        onFieldSubmitted: (_) => _submit(),
                        decoration: InputDecoration(
                          labelText: context.t('Verification code'),
                          prefixIcon: const Icon(Icons.pin_outlined),
                        ),
                        validator: (value) => (value == null || value.trim().length < 4)
                            ? 'Enter the code you received'
                            : null,
                      ),

                    if (_debugOtp != null) ...[
                      const SizedBox(height: 10),
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: AppColors.softTint(AppColors.warning, Theme.of(context).brightness),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.info_outline, size: 16, color: AppColors.warning),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'Dev mode — your code is $_debugOtp',
                                style: const TextStyle(
                                  color: AppColors.warning,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],

                    const SizedBox(height: 22),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: _busy
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : Text(
                              _useOtp
                                  ? (_otpSent ? 'Verify and sign in' : 'Send code')
                                  : 'Sign in',
                            ),
                    ),
                    const SizedBox(height: 10),
                    TextButton.icon(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                                _useOtp = !_useOtp;
                                _otpSent = false;
                                _debugOtp = null;
                              }),
                      icon: Icon(
                        _useOtp ? Icons.password_outlined : Icons.sms_outlined,
                        size: 18,
                      ),
                      label: Text(
                        _useOtp ? 'Use password instead' : 'Sign in with a code instead',
                      ),
                    ),

                    GoogleButton(enabled: !_busy),

                    const SizedBox(height: 18),
                    Row(
                      children: [
                        const Expanded(child: Divider()),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          child: Text(
                            'New here?',
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                          ),
                        ),
                        const Expanded(child: Divider()),
                      ],
                    ),
                    const SizedBox(height: 14),
                    OutlinedButton.icon(
                      onPressed: _busy ? null : () => context.goNamed(Routes.register),
                      icon: const Icon(Icons.storefront_outlined, size: 20),
                      label: Text(context.t('Create your shop account')),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
