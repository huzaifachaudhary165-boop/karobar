import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/validators.dart';
import '../../core/widgets/common.dart';
import '../../providers.dart';

/// Resetting a forgotten password, in three steps on one screen.
///
/// One screen rather than three routes, because the previous flow pushed a new
/// route per step and the code-entry step had no way back at all — a shopkeeper
/// who mistyped their email was stuck there and had to kill the app. Here every
/// step is a state of the same screen, the back arrow always moves one step
/// towards where you came from, and the hardware back button does the same.
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

enum _Step { identify, verify, done }

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _identifyKey = GlobalKey<FormState>();
  final _verifyKey = GlobalKey<FormState>();

  final _identifier = TextEditingController();
  final _code = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();

  _Step _step = _Step.identify;
  bool _busy = false;
  bool _obscure = true;
  String? _notice;
  String? _debugCode;

  @override
  void dispose() {
    _identifier.dispose();
    _code.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  /// The single definition of "back" — the app bar arrow, the hardware button
  /// and the text link all route through this, so they cannot disagree.
  void _back() {
    if (_step == _Step.verify) {
      setState(() {
        _step = _Step.identify;
        _notice = null;
        _debugCode = null;
        _code.clear();
      });
      return;
    }
    if (context.canPop()) {
      context.pop();
    } else {
      context.goNamed(Routes.login);
    }
  }

  Future<void> _sendCode() async {
    if (!_identifyKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _notice = null;
    });

    try {
      final sent = await ref
          .read(authRepositoryProvider)
          .sendResetCode(_identifier.text.trim());
      if (!mounted) return;

      setState(() {
        _step = _Step.verify;
        _debugCode = sent.debugCode;
        // When the send failed the code is still valid, so the flow continues —
        // it just must not tell anyone to go and look in an empty inbox.
        _notice = sent.delivered ? null : sent.message;
      });
    } catch (error) {
      // Stays on this step on purpose: the address they typed is right here to
      // be corrected.
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _resetPassword() async {
    if (!_verifyKey.currentState!.validate()) return;
    setState(() => _busy = true);

    try {
      await ref.read(authRepositoryProvider).resetPassword(
            identifier: _identifier.text.trim(),
            code: _code.text.trim(),
            newPassword: _password.text,
          );
      if (mounted) setState(() => _step = _Step.done);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return PopScope(
      // The system back gesture must step backwards through the flow rather
      // than abandoning it, so it is intercepted while there is a step to
      // return to.
      canPop: _step == _Step.identify,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        appBar: AppBar(
          leading: _step == _Step.done
              ? null
              : IconButton(
                  icon: const Icon(Icons.arrow_back),
                  onPressed: _busy ? null : _back,
                  tooltip: context.t('Back'),
                ),
          title: Text(context.t('Reset your password')),
        ),
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: switch (_step) {
                  _Step.identify => _identifyForm(theme),
                  _Step.verify => _verifyForm(theme),
                  _Step.done => _doneView(theme),
                },
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _identifyForm(ThemeData theme) {
    return Form(
      key: _identifyKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Header(
            icon: Icons.lock_reset,
            title: context.t('Forgot your password?'),
            body: context.t(
              'Enter the email address on your account and we will send you a '
              'code to set a new password.',
            ),
          ),
          const SizedBox(height: 26),
          TextFormField(
            controller: _identifier,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.done,
            autocorrect: false,
            autofillHints: const [AutofillHints.username],
            // Errors appear as soon as a field has been touched and left, not
            // only after the button is pressed.
            autovalidateMode: AutovalidateMode.onUserInteraction,
            onFieldSubmitted: (_) => _sendCode(),
            decoration: InputDecoration(
              labelText: context.t('Email address'),
              prefixIcon: const Icon(Icons.mail_outline),
            ),
            validator: Validators.email(context),
          ),
          const SizedBox(height: 8),
          Text(
            context.t(
              'Password reset by SMS is not available yet, so this needs the '
              'email address you signed up with.',
            ),
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 22),
          FilledButton(
            onPressed: _busy ? null : _sendCode,
            child: _busy ? const _ButtonSpinner() : Text(context.t('Send me a code')),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _busy ? null : _back,
            child: Text(context.t('Back to sign in')),
          ),
        ],
      ),
    );
  }

  Widget _verifyForm(ThemeData theme) {
    return Form(
      key: _verifyKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Header(
            icon: Icons.mark_email_read_outlined,
            title: context.t('Check your email'),
            body: '${context.t('We sent a code to')} ${_identifier.text.trim()}',
          ),

          if (_notice != null) ...[
            const SizedBox(height: 16),
            _Banner(
              tone: AppColors.warning,
              icon: Icons.warning_amber_rounded,
              text: _notice!,
            ),
          ],
          if (_debugCode != null) ...[
            const SizedBox(height: 10),
            _Banner(
              tone: AppColors.info,
              icon: Icons.info_outline,
              text: '${context.t('Test mode — your code is')} $_debugCode',
            ),
          ],

          const SizedBox(height: 22),
          TextFormField(
            controller: _code,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.next,
            autofillHints: const [AutofillHints.oneTimeCode],
            autovalidateMode: AutovalidateMode.onUserInteraction,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: InputDecoration(
              labelText: context.t('Code from the email'),
              prefixIcon: const Icon(Icons.pin_outlined),
            ),
            validator: (value) => (value == null || value.trim().length < 4)
                ? context.t('Enter the code from the email')
                : null,
          ),
          const SizedBox(height: 14),

          TextFormField(
            controller: _password,
            obscureText: _obscure,
            textInputAction: TextInputAction.next,
            autofillHints: const [AutofillHints.newPassword],
            autovalidateMode: AutovalidateMode.onUserInteraction,
            decoration: InputDecoration(
              labelText: context.t('New password'),
              prefixIcon: const Icon(Icons.lock_outline),
              suffixIcon: IconButton(
                icon: Icon(
                  _obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                ),
                onPressed: () => setState(() => _obscure = !_obscure),
              ),
            ),
            validator: Validators.password(context),
            onChanged: (_) => setState(() {}),
          ),
          PasswordStrengthHint(password: _password.text),
          const SizedBox(height: 14),

          TextFormField(
            controller: _confirm,
            obscureText: _obscure,
            textInputAction: TextInputAction.done,
            autovalidateMode: AutovalidateMode.onUserInteraction,
            onFieldSubmitted: (_) => _resetPassword(),
            decoration: InputDecoration(
              labelText: context.t('Confirm new password'),
              prefixIcon: const Icon(Icons.lock_outline),
            ),
            validator: (value) => value != _password.text
                ? context.t('Both passwords must match')
                : null,
          ),

          const SizedBox(height: 22),
          FilledButton(
            onPressed: _busy ? null : _resetPassword,
            child: _busy ? const _ButtonSpinner() : Text(context.t('Set new password')),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: _busy ? null : _back,
            icon: const Icon(Icons.arrow_back, size: 18),
            label: Text(context.t('Use a different email')),
          ),
        ],
      ),
    );
  }

  Widget _doneView(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Header(
          icon: Icons.check_circle_outline,
          tone: AppColors.success,
          title: context.t('Password changed'),
          body: context.t('You can sign in with your new password now.'),
        ),
        const SizedBox(height: 28),
        FilledButton(
          onPressed: () => context.goNamed(Routes.login),
          child: Text(context.t('Go to sign in')),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.icon,
    required this.title,
    required this.body,
    this.tone = AppColors.primary,
  });

  final IconData icon;
  final String title;
  final String body;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      children: [
        Container(
          width: 72,
          height: 72,
          decoration: BoxDecoration(
            color: AppColors.softTint(tone, theme.brightness),
            shape: BoxShape.circle,
          ),
          child: Icon(icon, size: 34, color: tone),
        ),
        const SizedBox(height: 20),
        Text(
          title,
          textAlign: TextAlign.center,
          style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 8),
        Text(
          body,
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
            height: 1.5,
          ),
        ),
      ],
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.tone, required this.icon, required this.text});

  final Color tone;
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.softTint(tone, brightness),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: AppColors.onSoftTint(tone, brightness)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                color: AppColors.onSoftTint(tone, brightness),
                fontSize: 12.5,
                height: 1.4,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ButtonSpinner extends StatelessWidget {
  const _ButtonSpinner();

  @override
  Widget build(BuildContext context) => const SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
      );
}
