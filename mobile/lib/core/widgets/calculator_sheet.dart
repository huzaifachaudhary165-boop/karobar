import 'package:flutter/material.dart';

import '../../data/models.dart' show trimZeros;
import '../l10n/strings.dart';
import '../theme/app_colors.dart';

/// The calculator a shopkeeper would otherwise leave the app to find.
///
/// Not a general one. A wholesaler works in the same three shapes all day —
/// how much for this many, what is that less a percent, and what does the
/// running column come to — and a phone's calculator gives none of them back
/// as anything the bill can use. Leaving the app to do arithmetic is also how
/// a half-finished bill gets lost.
///
/// [onUse] is what makes it part of Karobar rather than a calculator that
/// happens to live here: the answer goes back to whatever asked for it — a
/// rate, a quantity, an amount received.
Future<double?> showCalculator(
  BuildContext context, {
  double? start,
  String? title,
}) {
  return showModalBottomSheet<double>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _CalculatorSheet(start: start, title: title),
  );
}

/// The keypad itself, without the sheet around it.
///
/// Shown inline on the calculator screen's first tab and inside the bottom
/// sheet when a field asks for a number. [onUse] is what makes it the second
/// of those: with it, the answer is handed back; without it, there is nothing
/// to hand it to and the button is left off.
class CalculatorPad extends StatefulWidget {
  const CalculatorPad({super.key, this.start, this.title, this.onUse});

  final double? start;
  final String? title;
  final ValueChanged<double>? onUse;

  @override
  State<CalculatorPad> createState() => _CalculatorPadState();
}

class _CalculatorSheet extends StatefulWidget {
  const _CalculatorSheet({this.start, this.title});

  final double? start;
  final String? title;

  @override
  State<_CalculatorSheet> createState() => _CalculatorSheetState();
}

/// The sheet is the pad plus a way back out with the answer.
class _CalculatorSheetState extends State<_CalculatorSheet> {
  @override
  Widget build(BuildContext context) => CalculatorPad(
        start: widget.start,
        title: widget.title,
        onUse: (value) => Navigator.pop(context, value),
      );
}

class _CalculatorPadState extends State<CalculatorPad> {
  /// What is on the display right now, as typed.
  String _entry = '0';

  /// The left-hand side of a pending operation, and which operation it is.
  double? _pending;
  String? _operator;

  /// Whether the next digit starts a new number rather than extending this one.
  bool _fresh = true;

  /// Every step, kept and shown.
  ///
  /// A shopkeeper adding thirty rows needs to see what has gone in — a running
  /// total with no history is a number you have to trust, and the reason
  /// people reach for a paper roll instead.
  final _tape = <String>[];

  @override
  void initState() {
    super.initState();
    if (widget.start != null && widget.start != 0) {
      _entry = trimZeros(widget.start!);
      _fresh = true;
    }
  }

  double get _value => double.tryParse(_entry) ?? 0;

  void _digit(String d) {
    setState(() {
      if (_fresh) {
        _entry = d == '.' ? '0.' : d;
        _fresh = false;
        return;
      }
      if (d == '.' && _entry.contains('.')) return;
      if (_entry == '0' && d != '.') {
        _entry = d;
        return;
      }
      _entry += d;
    });
  }

  void _clear() => setState(() {
        _entry = '0';
        _pending = null;
        _operator = null;
        _fresh = true;
        _tape.clear();
      });

  void _back() => setState(() {
        if (_fresh || _entry.length <= 1) {
          _entry = '0';
          _fresh = true;
        } else {
          _entry = _entry.substring(0, _entry.length - 1);
        }
      });

  double _apply(double left, double right, String op) => switch (op) {
        '+' => left + right,
        '-' => left - right,
        '×' => left * right,
        // A shop divides by a count — bori into kilos, carton into pieces —
        // and dividing by nothing is a slip, not an answer.
        '÷' => right == 0 ? left : left / right,
        _ => right,
      };

  void _operate(String op) {
    setState(() {
      if (_pending != null && _operator != null && !_fresh) {
        final result = _apply(_pending!, _value, _operator!);
        _tape.add('${trimZeros(_pending!)} $_operator ${trimZeros(_value)} = '
            '${trimZeros(result)}');
        _pending = result;
        _entry = trimZeros(result);
      } else {
        _pending = _value;
      }
      _operator = op;
      _fresh = true;
    });
  }

  void _equals() {
    if (_pending == null || _operator == null) return;
    setState(() {
      final result = _apply(_pending!, _value, _operator!);
      _tape.add('${trimZeros(_pending!)} $_operator ${trimZeros(_value)} = '
          '${trimZeros(result)}');
      _entry = trimZeros(result);
      _pending = null;
      _operator = null;
      _fresh = true;
    });
  }

  /// The plain percent key, meaning what a shop means by it.
  ///
  /// With a sum waiting it is a share of the left-hand side, so "1000 − 10 %"
  /// takes off 100. A scientific calculator gives 0.1 there, which is not what
  /// anybody at a counter is asking for. On its own it divides by a hundred.
  void _sharePercent() => setState(() {
        if (_pending != null && _operator != null) {
          _entry = trimZeros(_pending! * _value / 100);
        } else {
          _entry = trimZeros(_value / 100);
        }
        _fresh = false;
      });

  /// Adds or removes a percentage of what is on the display.
  ///
  /// Not the percent key a scientific calculator has. In a shop "10% off" and
  /// "17% tax on top" are the two things anybody means, and both of them are a
  /// whole answer rather than a step.
  void _percent(int percent, {required bool add}) {
    setState(() {
      final base = _value;
      final delta = base * percent / 100;
      final result = add ? base + delta : base - delta;
      _tape.add('${trimZeros(base)} ${add ? '+' : '-'} $percent% = '
          '${trimZeros(result)}');
      _entry = trimZeros(result);
      _fresh = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (widget.title != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                  context.t(widget.title!),
                  style: theme.textTheme.titleSmall,
                ),
              ),

            // The tape. Newest at the bottom, the way a paper roll reads.
            if (_tape.isNotEmpty)
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 76),
                child: SingleChildScrollView(
                  reverse: true,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      for (final line in _tape)
                        Text(
                          line,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                    ],
                  ),
                ),
              ),

            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                _operator == null
                    ? _entry
                    : '${trimZeros(_pending ?? 0)} $_operator '
                        '${_fresh ? '' : _entry}',
                textAlign: TextAlign.right,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.displaySmall?.copyWith(
                  fontWeight: FontWeight.w700,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ),

            // The two a shop actually reaches for, spelled out rather than
            // hidden behind a % key nobody agrees on the meaning of.
            Row(
              children: [
                for (final (label, pct, add) in [
                  ('−10%', 10, false),
                  ('−5%', 5, false),
                  ('+17%', 17, true),
                ]) ...[
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => _percent(pct, add: add),
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                      ),
                      child: Text(label, style: const TextStyle(fontSize: 13)),
                    ),
                  ),
                  const SizedBox(width: 6),
                ],
              ],
            ),
            const SizedBox(height: 6),

            for (final row in const [
              ['C', '⌫', '%', '÷'],
              ['7', '8', '9', '×'],
              ['4', '5', '6', '-'],
              ['1', '2', '3', '+'],
              ['0', '.', '000', '='],
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    for (final key in row) ...[
                      Expanded(
                        child: key.isEmpty
                            ? const SizedBox.shrink()
                            : _Key(
                                label: key,
                                onTap: () => _press(key),
                              ),
                      ),
                      const SizedBox(width: 6),
                    ],
                  ],
                ),
              ),

            // Only when there is somewhere to hand the answer back to. On the
            // calculator screen the answer is the point in itself.
            if (widget.onUse != null) ...[
              const SizedBox(height: 2),
              SizedBox(
                height: 46,
                child: FilledButton.icon(
                  onPressed: () {
                    // Settle any half-finished sum first, so "12 × 8" then Use
                    // hands back 96 rather than the 8 still on the display.
                    _equals();
                    widget.onUse!(_value);
                  },
                  icon: const Icon(Icons.check, size: 18),
                  label: Text(context.t('Use this number')),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _press(String key) {
    switch (key) {
      case 'C':
        _clear();
      case '⌫':
        _back();
      case '=':
        _equals();
      case '%':
        _sharePercent();
      case '+' || '-' || '×' || '÷':
        _operate(key);
      case '000':
        // One tap for a thousand. A wholesaler types these all day.
        for (var i = 0; i < 3; i++) {
          _digit('0');
        }
      default:
        _digit(key);
    }
  }
}

class _Key extends StatelessWidget {
  const _Key({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  bool get _isOperator => const {'+', '-', '×', '÷', '='}.contains(label);
  bool get _isClear => label == 'C' || label == '⌫';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tint = _isOperator
        ? AppColors.primary
        : _isClear
            ? AppColors.danger
            : theme.colorScheme.onSurface;

    return SizedBox(
      height: 48,
      child: Material(
        color: _isOperator
            ? AppColors.primary.withValues(alpha: 0.1)
            : theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Center(
            child: Text(
              label,
              style: theme.textTheme.titleMedium?.copyWith(
                color: tint,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
