import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/utils/validators.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';

/// Sign in with an email or phone number and a password.
///
/// Sign-in by one-time code used to live here too. It is gone because no SMS
/// provider is configured, so the code was never delivered — the screen asked
/// for a number, said a code had been sent, and then waited for something that
/// was never going to arrive. "Continue with Google" is gone for the same kind
/// of reason: it needs an Android OAuth client that does not exist yet, so on a
/// real phone it failed on tap.
///
/// A sign-in route that cannot work is worse than one that is absent: it costs
/// the shopkeeper time and makes them doubt the password they typed correctly.
/// Both come back when the service behind them does.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _identifier = TextEditingController();
  final _password = TextEditingController();

  bool _busy = false;
  bool _obscure = true;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);

    try {
      await ref
          .read(sessionProvider.notifier)
          .login(_identifier.text.trim(), _password.text);
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
                      context.t('Welcome back'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      context.t('Sign in to your shop'),
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                    const SizedBox(height: 28),

                    TextFormField(
                      controller: _identifier,
                      keyboardType: TextInputType.emailAddress,
                      textInputAction: TextInputAction.next,
                      autocorrect: false,
                      autofillHints: const [AutofillHints.username],
                      // Says what is wrong while the field is still in front of
                      // them, instead of waiting for the button to be pressed.
                      autovalidateMode: AutovalidateMode.onUserInteraction,
                      decoration: InputDecoration(
                        labelText: context.t('Email or phone number'),
                        prefixIcon: const Icon(Icons.person_outline),
                      ),
                      validator: Validators.emailOrPhone(context),
                    ),
                    const SizedBox(height: 14),

                    TextFormField(
                      controller: _password,
                      obscureText: _obscure,
                      textInputAction: TextInputAction.done,
                      autofillHints: const [AutofillHints.password],
                      autovalidateMode: AutovalidateMode.onUserInteraction,
                      onFieldSubmitted: (_) => _submit(),
                      decoration: InputDecoration(
                        labelText: context.t('Password'),
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscure
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                          tooltip: context.t(_obscure ? 'Show password' : 'Hide password'),
                          onPressed: () => setState(() => _obscure = !_obscure),
                        ),
                      ),
                      // Not the strength rules: an existing password was valid
                      // when it was chosen, and telling someone it needs a
                      // number while they are signing in is nonsense.
                      validator: (value) => (value == null || value.isEmpty)
                          ? context.t('Enter your password')
                          : null,
                    ),

                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: TextButton(
                        onPressed: _busy
                            ? null
                            : () => context.pushNamed(Routes.forgotPassword),
                        child: Text(context.t('Forgot password?')),
                      ),
                    ),

                    const SizedBox(height: 10),
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
                          : Text(context.t('Sign in')),
                    ),

                    const SizedBox(height: 22),
                    Row(
                      children: [
                        const Expanded(child: Divider()),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          child: Text(
                            context.t('New here?'),
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
