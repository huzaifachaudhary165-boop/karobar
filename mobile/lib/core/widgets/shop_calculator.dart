import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../theme/app_colors.dart';
import '../utils/calculator_engine.dart';

/// The calculator a shop counter already has, on screen.
///
/// Laid out like the desktop machine people here own: memory keys across the
/// top, the grand total beside them, and the digits where the hand expects
/// them. A shopkeeper has muscle memory for that arrangement, and one they
/// have to read before every press is one they go back to their own machine
/// for.
///
/// [onUse] is what makes it part of Karobar rather than a calculator that
/// happens to live here — the answer goes back to the field that asked for it.
/// Without it the button is left off, because on the calculator screen the
/// answer is the point in itself.
class ShopCalculator extends StatefulWidget {
  const ShopCalculator({super.key, this.start, this.onUse});

  final double? start;
  final ValueChanged<double>? onUse;

  @override
  State<ShopCalculator> createState() => _ShopCalculatorState();
}

class _ShopCalculatorState extends State<ShopCalculator> {
  final _c = CalculatorEngine();

  @override
  void initState() {
    super.initState();
    if (widget.start != null && widget.start != 0) {
      _c.entry = CalculatorEngine.format(widget.start!);
    }
  }

  void _press(void Function() action) => setState(action);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Display(engine: _c),
        const SizedBox(height: 14),

        // Memory and the running total. Set apart from the digits because
        // they are the keys somebody reaches for deliberately, not while
        // typing.
        _Row(children: [
          _Key('MC', kind: _Kind.memory, onTap: () => _press(_c.memoryClear)),
          _Key('MR', kind: _Kind.memory, onTap: () => _press(_c.memoryRecall)),
          _Key('M−', kind: _Kind.memory, onTap: () => _press(_c.memorySubtract)),
          _Key('M+', kind: _Kind.memory, onTap: () => _press(_c.memoryAdd)),
          _Key(
            'GT',
            kind: _Kind.memory,
            onTap: () => _press(_c.showGrandTotal),
            // Held down to clear it, the way the machine does — so the total
            // of a long column cannot be lost by a stray tap.
            onLongPress: () => _press(_c.clearGrandTotal),
          ),
        ]),

        _Row(children: [
          _Key('AC', kind: _Kind.clear, onTap: () => _press(_c.allClear)),
          _Key('C', kind: _Kind.clear, onTap: () => _press(_c.clearEntry)),
          _Key('⌫', kind: _Kind.clear, onTap: () => _press(_c.backspace)),
          _Key('√', kind: _Kind.function, onTap: () => _press(_c.squareRoot)),
          _Key('÷', kind: _Kind.operator, onTap: () => _press(() => _c.operate('÷'))),
        ]),

        _Row(children: [
          _Key('7', onTap: () => _press(() => _c.digit('7'))),
          _Key('8', onTap: () => _press(() => _c.digit('8'))),
          _Key('9', onTap: () => _press(() => _c.digit('9'))),
          _Key('%', kind: _Kind.function, onTap: () => _press(_c.percent)),
          _Key('×', kind: _Kind.operator, onTap: () => _press(() => _c.operate('×'))),
        ]),

        _Row(children: [
          _Key('4', onTap: () => _press(() => _c.digit('4'))),
          _Key('5', onTap: () => _press(() => _c.digit('5'))),
          _Key('6', onTap: () => _press(() => _c.digit('6'))),
          _Key('±', kind: _Kind.function, onTap: () => _press(_c.toggleSign)),
          _Key('−', kind: _Kind.operator, onTap: () => _press(() => _c.operate('−'))),
        ]),

        _Row(children: [
          _Key('1', onTap: () => _press(() => _c.digit('1'))),
          _Key('2', onTap: () => _press(() => _c.digit('2'))),
          _Key('3', onTap: () => _press(() => _c.digit('3'))),
          // Two zeros and three, because a wholesaler types thousands and
          // lakhs all day and every one of these is a keystroke saved.
          _Key('00', onTap: () => _press(() {
                _c.digit('0');
                _c.digit('0');
              })),
          _Key('+', kind: _Kind.operator, onTap: () => _press(() => _c.operate('+'))),
        ]),

        _Row(children: [
          _Key('0', flex: 2, onTap: () => _press(() => _c.digit('0'))),
          _Key('.', onTap: () => _press(() => _c.digit('.'))),
          _Key('000', onTap: () => _press(() {
                _c.digit('0');
                _c.digit('0');
                _c.digit('0');
              })),
          _Key('=', kind: _Kind.equals, onTap: () => _press(_c.equals)),
        ]),

        if (widget.onUse != null) ...[
          const SizedBox(height: 10),
          SizedBox(
            height: 48,
            child: FilledButton.icon(
              onPressed: () {
                // Settles any half-finished sum first, so "12 × 8" then Use
                // hands back 96 rather than the 8 still on the display.
                setState(_c.equals);
                widget.onUse!(_c.value);
              },
              icon: const Icon(Icons.check, size: 18),
              label: Text(context.t('Use this number')),
            ),
          ),
        ],

        const SizedBox(height: 6),
        Text(
          context.t('Hold GT to clear the running total'),
          textAlign: TextAlign.center,
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }
}

/// The panel above the keys.
///
/// Carries **M** and **GT** markers, because a figure sitting in memory that
/// nobody can see is a figure that gets used by accident on the next sum.
class _Display extends StatelessWidget {
  const _Display({required this.engine});

  final CalculatorEngine engine;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              if (engine.hasMemory)
                _Marker('M ${CalculatorEngine.format(engine.memory)}'),
              if (engine.hasMemory && engine.hasGrandTotal)
                const SizedBox(width: 8),
              if (engine.hasGrandTotal)
                _Marker('GT ${CalculatorEngine.format(engine.grandTotal)}'),
              const Spacer(),
              if (engine.lastSum != null)
                Flexible(
                  child: Text(
                    engine.lastSum!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.right,
                    style: theme.textTheme.bodySmall?.copyWith(color: muted),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 6),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerRight,
            child: Text(
              engine.display,
              maxLines: 1,
              style: theme.textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w700,
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Marker extends StatelessWidget {
  const _Marker(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: AppColors.primary.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: AppColors.primary,
              fontWeight: FontWeight.w700,
            ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          for (final (index, child) in children.indexed) ...[
            if (index > 0) const SizedBox(width: 8),
            child,
          ],
        ],
      ),
    );
  }
}

enum _Kind { digit, operator, equals, clear, memory, function }

class _Key extends StatelessWidget {
  const _Key(
    this.label, {
    required this.onTap,
    this.kind = _Kind.digit,
    this.flex = 1,
    this.onLongPress,
  });

  final String label;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;
  final _Kind kind;
  final int flex;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    final (background, foreground) = switch (kind) {
      _Kind.equals => (AppColors.primary, Colors.white),
      _Kind.operator => (
          AppColors.primary.withValues(alpha: 0.14),
          AppColors.primary,
        ),
      _Kind.clear => (
          AppColors.danger.withValues(alpha: 0.12),
          AppColors.danger,
        ),
      // Muted, because these are reached for deliberately and should not
      // compete with the digits for the eye.
      _Kind.memory || _Kind.function => (
          scheme.surfaceContainerHighest,
          scheme.onSurfaceVariant,
        ),
      _Kind.digit => (scheme.surfaceContainerHigh, scheme.onSurface),
    };

    return Expanded(
      flex: flex,
      child: SizedBox(
        height: 56,
        child: Material(
          color: background,
          borderRadius: BorderRadius.circular(14),
          child: InkWell(
            onTap: onTap,
            onLongPress: onLongPress,
            borderRadius: BorderRadius.circular(14),
            child: Center(
              child: Text(
                label,
                style: (kind == _Kind.memory
                        ? theme.textTheme.labelLarge
                        : theme.textTheme.titleLarge)
                    ?.copyWith(color: foreground, fontWeight: FontWeight.w700),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
