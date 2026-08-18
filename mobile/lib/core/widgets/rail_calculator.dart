import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../theme/app_colors.dart';
import '../../data/models.dart' show trimZeros;

/// A calculator that lives in the side rail and is always there.
///
/// The rail on a wide screen is four destinations and then a column of empty
/// space to the bottom of the window. A shopkeeper with a laptop keeps a
/// calculator open beside their work anyway — this is that calculator, in the
/// space that was doing nothing.
///
/// Deliberately not the module. That has margin, discounts, tax and units, and
/// is a screen you go to on purpose. This is the one you glance at mid-bill:
/// digits, four operations, percent, and nothing to learn.
class RailCalculator extends StatefulWidget {
  const RailCalculator({super.key, this.width = 172});

  /// Its own width, because the slot it sits in does not give it one.
  ///
  /// `NavigationRail` hands `trailing` unbounded width, so a child that
  /// stretches — as a keypad must — asks for infinity and throws during
  /// layout. That took the whole screen down once already: the app bar painted
  /// and everything under it was black.
  final double width;

  @override
  State<RailCalculator> createState() => _RailCalculatorState();
}

class _RailCalculatorState extends State<RailCalculator> {
  String _entry = '0';
  double? _pending;
  String? _operator;
  bool _fresh = true;

  /// The last completed sum, kept above the display.
  ///
  /// One line, not a tape: there is no room for a tape here, and the thing
  /// people actually look back at is the answer before this one.
  String? _last;

  double get _value => double.tryParse(_entry) ?? 0;

  void _digit(String d) => setState(() {
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

  double _apply(double a, double b, String op) => switch (op) {
        '+' => a + b,
        '−' => a - b,
        '×' => a * b,
        // Dividing by nothing is a slip, not an answer — infinity on a rate is
        // worse than the number they started from.
        '÷' => b == 0 ? a : a / b,
        _ => b,
      };

  void _operate(String op) => setState(() {
        if (_pending != null && _operator != null && !_fresh) {
          final result = _apply(_pending!, _value, _operator!);
          _last = '${trimZeros(_pending!)} $_operator ${trimZeros(_value)}';
          _pending = result;
          _entry = trimZeros(result);
        } else {
          _pending = _value;
        }
        _operator = op;
        _fresh = true;
      });

  void _equals() {
    if (_pending == null || _operator == null) return;
    setState(() {
      final result = _apply(_pending!, _value, _operator!);
      _last = '${trimZeros(_pending!)} $_operator ${trimZeros(_value)} =';
      _entry = trimZeros(result);
      _pending = null;
      _operator = null;
      _fresh = true;
    });
  }

  /// Percent, meaning what a shop means by it.
  ///
  /// With a sum waiting it is a share of the left-hand side — "1000 − 10%"
  /// takes 100 off, which is what everybody expects and what a scientific
  /// calculator does not do. On its own it just divides by a hundred.
  void _percent() => setState(() {
        if (_pending != null && _operator != null) {
          _entry = trimZeros(_pending! * _value / 100);
        } else {
          _entry = trimZeros(_value / 100);
        }
        _fresh = false;
      });

  void _clear() => setState(() {
        _entry = '0';
        _pending = null;
        _operator = null;
        _fresh = true;
        _last = null;
      });

  void _back() => setState(() {
        if (_fresh || _entry.length <= 1) {
          _entry = '0';
          _fresh = true;
        } else {
          _entry = _entry.substring(0, _entry.length - 1);
        }
      });

  void _press(String key) {
    switch (key) {
      case 'C':
        _clear();
      case '⌫':
        _back();
      case '=':
        _equals();
      case '%':
        _percent();
      case '+' || '−' || '×' || '÷':
        _operate(key);
      default:
        _digit(key);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SizedBox(
      width: widget.width,
      child: Padding(
      padding: const EdgeInsets.fromLTRB(6, 0, 6, 8),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Divider(height: 12),
          Row(
            children: [
              const Icon(Icons.calculate_outlined,
                  size: 13, color: AppColors.primary),
              const SizedBox(width: 4),
              Text(
                context.t('Calculator'),
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
          const SizedBox(height: 4),

          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (_last != null)
                  Text(
                    _last!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                Text(
                  _operator == null
                      ? _entry
                      : '${trimZeros(_pending ?? 0)} $_operator'
                          '${_fresh ? '' : ' $_entry'}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 5),

          for (final row in const [
            ['C', '⌫', '%', '÷'],
            ['7', '8', '9', '×'],
            ['4', '5', '6', '−'],
            ['1', '2', '3', '+'],
            ['0', '.', '='],
          ])
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                children: [
                  for (final key in row) ...[
                    Expanded(
                      // The last row is three keys across four columns, so "0"
                      // takes the extra width the way every phone keypad does.
                      flex: row.length == 3 && key == '0' ? 2 : 1,
                      child: _RailKey(label: key, onTap: () => _press(key)),
                    ),
                    const SizedBox(width: 4),
                  ],
                ],
              ),
            ),
        ],
      ),
      ),
    );
  }
}

class _RailKey extends StatelessWidget {
  const _RailKey({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  bool get _isOperator => const {'+', '−', '×', '÷', '=', '%'}.contains(label);
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
      height: 32,
      child: Material(
        color: _isOperator
            ? AppColors.primary.withValues(alpha: 0.12)
            : theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(7),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(7),
          child: Center(
            child: Text(
              label,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: tint, fontWeight: FontWeight.w700),
            ),
          ),
        ),
      ),
    );
  }
}
