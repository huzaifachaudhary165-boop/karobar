import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../theme/app_colors.dart';

/// Field validators, worded so that the message says what to *do*.
///
/// These deliberately mirror `password_strength_issues` in the backend
/// (`backend/app/core/security.py`) rule for rule. When the two disagree the
/// form accepts a password, the request is sent, and the server rejects it with
/// a message that arrives too late to be attached to the field — which is
/// exactly what made a failed sign-up look like it had no reason.
///
/// If the backend rule changes, change [passwordProblems] with it.
abstract final class Validators {
  /// The backend's rules, in the same order it reports them.
  ///
  /// Unicode-aware on purpose. The backend asks Python for `c.isalpha()` and
  /// `c.isdigit()`, both of which accept any script — so a password written in
  /// Urdu satisfies the server. An ASCII `[A-Za-z]` here would reject it on the
  /// phone, leaving a shopkeeper unable to sign up at all with a password the
  /// server would have been perfectly happy with.
  static List<String> passwordProblems(String password) => [
        if (password.length < 8) 'at least 8 characters',
        if (!password.contains(_anyDigit)) 'a number',
        if (!password.contains(_anyLetter)) 'a letter',
      ];

  static final _anyLetter = RegExp(r'\p{L}', unicode: true);
  static final _anyDigit = RegExp(r'\p{Nd}', unicode: true);

  static String? Function(String?) password(BuildContext context) => (value) {
        final text = value ?? '';
        if (text.isEmpty) return context.t('Choose a password');

        final problems = passwordProblems(text);
        if (problems.isEmpty) return null;

        // "Password needs a number" beats "invalid password": it names the one
        // thing missing rather than leaving someone to guess.
        return '${context.t('Password needs')} ${_join(context, problems)}';
      };

  static String? Function(String?) email(BuildContext context) => (value) {
        final text = (value ?? '').trim();
        if (text.isEmpty) return context.t('Enter your email address');
        if (!_emailPattern.hasMatch(text)) {
          return context.t('That does not look like an email address');
        }
        return null;
      };

  /// Accepts either an email or a phone number, since sign-in takes both.
  static String? Function(String?) emailOrPhone(BuildContext context) => (value) {
        final text = (value ?? '').trim();
        if (text.isEmpty) return context.t('Enter your email or phone number');
        if (text.contains('@')) return email(context)(text);
        if (_phonePattern.hasMatch(text)) return null;
        return context.t('Enter a valid email address or phone number');
      };

  static String? Function(String?) required(BuildContext context, String label) =>
      (value) => (value == null || value.trim().isEmpty)
          ? '${context.t('Please enter')} ${context.t(label)}'
          : null;

  static String? Function(String?) minLength(
    BuildContext context,
    String label,
    int length,
  ) =>
      (value) {
        final text = (value ?? '').trim();
        if (text.isEmpty) return '${context.t('Please enter')} ${context.t(label)}';
        if (text.length < length) {
          return '${context.t(label)} ${context.t('must be at least')} $length '
              '${context.t('characters')}';
        }
        return null;
      };

  static final _emailPattern = RegExp(r'^[\w.!#$%&*+/=?^`{|}~-]+@[\w-]+(\.[\w-]+)+$');

  // Deliberately loose: shop phone numbers get written with spaces, dashes and
  // a country code, and rejecting those is more annoying than useful.
  static final _phonePattern = RegExp(r'^\+?[\d\s-]{7,20}$');

  static String _join(BuildContext context, List<String> parts) {
    final translated = parts.map(context.t).toList();
    if (translated.length == 1) return translated.first;
    return '${translated.sublist(0, translated.length - 1).join(', ')} '
        '${context.t('and')} ${translated.last}';
  }
}

/// A live checklist under a password field.
///
/// A validator only speaks when the form is submitted or the field is left.
/// This updates on every keystroke, so someone typing their first password can
/// see the requirements go green as they satisfy them instead of being told
/// afterwards that they got it wrong.
class PasswordStrengthHint extends StatelessWidget {
  const PasswordStrengthHint({super.key, required this.password});

  final String password;

  @override
  Widget build(BuildContext context) {
    // Nothing typed yet: showing three red crosses next to an empty box reads
    // as failure before the person has even started.
    if (password.isEmpty) return const SizedBox.shrink();

    final problems = Validators.passwordProblems(password);
    const rules = ['at least 8 characters', 'a number', 'a letter'];

    return Padding(
      padding: const EdgeInsets.only(top: 8, left: 4),
      child: Wrap(
        spacing: 14,
        runSpacing: 4,
        children: [
          for (final rule in rules)
            _RuleChip(label: context.t(rule), satisfied: !problems.contains(rule)),
        ],
      ),
    );
  }
}

class _RuleChip extends StatelessWidget {
  const _RuleChip({required this.label, required this.satisfied});

  final String label;
  final bool satisfied;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colour = satisfied
        ? AppColors.onSoftTint(AppColors.success, theme.brightness)
        : theme.colorScheme.onSurfaceVariant;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          satisfied ? Icons.check_circle : Icons.radio_button_unchecked,
          size: 14,
          color: colour,
        ),
        const SizedBox(width: 5),
        Text(
          label,
          style: theme.textTheme.bodySmall?.copyWith(
            color: colour,
            fontWeight: satisfied ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ],
    );
  }
}
