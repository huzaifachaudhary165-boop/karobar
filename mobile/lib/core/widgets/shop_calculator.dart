import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

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
  const ShopCalculator({
    super.key,
    this.start,
    this.onUse,
    this.framed = true,
    this.listenToKeyboard = true,
  });

  final double? start;
  final ValueChanged<double>? onUse;

  /// Whether to draw the body of the machine around the keys.
  ///
  /// Off inside a sheet, where the sheet is already the panel — a box inside a
  /// box is 40 wasted pixels, and on a small phone those are the ones that push
  /// the Use button below the fold.
  final bool framed;

  /// Whether to take the keyboard.
  ///
  /// The shell builds every tab at once and keeps them all alive, so a
  /// calculator that grabs the keyboard the moment it is built would swallow
  /// typing on the dashboard and quietly fill itself with digits nobody meant
  /// for it. Off while the tab is not the one on screen.
  final bool listenToKeyboard;

  @override
  State<ShopCalculator> createState() => _ShopCalculatorState();
}

class _ShopCalculatorState extends State<ShopCalculator> {
  final _c = CalculatorEngine();
  final _typing = FocusNode(debugLabel: 'calculator');

  @override
  void initState() {
    super.initState();
    if (widget.start != null && widget.start != 0) {
      _c.entry = CalculatorEngine.format(widget.start!);
    }
  }

  @override
  void didUpdateWidget(ShopCalculator old) {
    super.didUpdateWidget(old);
    // Takes the keyboard when the tab is opened, gives it back when it is left.
    if (widget.listenToKeyboard != old.listenToKeyboard) {
      if (widget.listenToKeyboard) {
        _typing.requestFocus();
      } else {
        _typing.unfocus();
      }
    }
  }

  @override
  void dispose() {
    _typing.dispose();
    super.dispose();
  }

  void _press(void Function() action) => setState(action);

  /// On a laptop the keyboard is right there, and somebody totalling a delivery
  /// note will type rather than aim a mouse at 4, then 5, then 0. Every key on
  /// the pad has the obvious equivalent, on the number row and on the numpad.
  ///
  /// Read off the logical key rather than the character it produces, because
  /// the numpad and the number row send the same key and not always the same
  /// character.
  KeyEventResult _typed(FocusNode _, KeyEvent event) {
    if (event is KeyUpEvent) return KeyEventResult.ignored;

    final action = _keyboard[event.logicalKey] ?? _byCharacter(event.character);
    if (action == null) return KeyEventResult.ignored;

    _press(action);
    return KeyEventResult.handled;
  }

  /// The fallback for layouts that put ×, ÷ or % behind a modifier.
  void Function()? _byCharacter(String? character) => switch (character) {
        '*' || 'x' || 'X' => () => _c.operate('×'),
        '/' => () => _c.operate('÷'),
        '+' => () => _c.operate('+'),
        '-' => () => _c.operate('−'),
        '=' => _c.equals,
        '%' => _c.percent,
        '.' => () => _c.digit('.'),
        'c' || 'C' => _c.clearEntry,
        final String ch when ch.length == 1 && '0123456789'.contains(ch) =>
          () => _c.digit(ch),
        _ => null,
      };

  late final Map<LogicalKeyboardKey, void Function()> _keyboard = {
    for (var n = 0; n <= 9; n++) ...{
      LogicalKeyboardKey(LogicalKeyboardKey.digit0.keyId + n): () =>
          _c.digit('$n'),
      LogicalKeyboardKey(LogicalKeyboardKey.numpad0.keyId + n): () =>
          _c.digit('$n'),
    },
    LogicalKeyboardKey.period: () => _c.digit('.'),
    LogicalKeyboardKey.numpadDecimal: () => _c.digit('.'),
    LogicalKeyboardKey.add: () => _c.operate('+'),
    LogicalKeyboardKey.numpadAdd: () => _c.operate('+'),
    LogicalKeyboardKey.minus: () => _c.operate('−'),
    LogicalKeyboardKey.numpadSubtract: () => _c.operate('−'),
    LogicalKeyboardKey.asterisk: () => _c.operate('×'),
    LogicalKeyboardKey.numpadMultiply: () => _c.operate('×'),
    LogicalKeyboardKey.slash: () => _c.operate('÷'),
    LogicalKeyboardKey.numpadDivide: () => _c.operate('÷'),
    LogicalKeyboardKey.percent: _c.percent,
    LogicalKeyboardKey.equal: _c.equals,
    LogicalKeyboardKey.enter: _c.equals,
    LogicalKeyboardKey.numpadEnter: _c.equals,
    LogicalKeyboardKey.numpadEqual: _c.equals,
    LogicalKeyboardKey.backspace: _c.backspace,
    LogicalKeyboardKey.delete: _c.clearEntry,
    LogicalKeyboardKey.escape: _c.allClear,
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final keys = Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Display(engine: _c),
        const SizedBox(height: 12),

                // Memory and the running total. Set apart from the digits
                // because they are the keys somebody reaches for deliberately,
                // not while typing.
                _Row(children: [
                  _Key('MC', kind: _Kind.memory, onTap: () => _press(_c.memoryClear)),
                  _Key('MR', kind: _Kind.memory, onTap: () => _press(_c.memoryRecall)),
                  _Key('M−', kind: _Kind.memory, onTap: () => _press(_c.memorySubtract)),
                  _Key('M+', kind: _Kind.memory, onTap: () => _press(_c.memoryAdd)),
                  _Key(
                    'GT',
                    kind: _Kind.memory,
                    onTap: () => _press(_c.showGrandTotal),
                    // Held down to clear it, the way the machine does — so the
                    // total of a long column cannot be lost by a stray tap.
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
                  // Two zeros and three, because a wholesaler types thousands
                  // and lakhs all day and every one of these is a keystroke
                  // saved.
                  _Key('00', onTap: () => _press(() {
                        _c.digit('0');
                        _c.digit('0');
                      })),
                  _Key('+', kind: _Kind.operator, onTap: () => _press(() => _c.operate('+'))),
                ]),

                _Row(
                  last: true,
                  children: [
                    _Key('0', flex: 2, onTap: () => _press(() => _c.digit('0'))),
                    _Key('.', onTap: () => _press(() => _c.digit('.'))),
                    _Key('000', onTap: () => _press(() {
                          _c.digit('0');
                          _c.digit('0');
                          _c.digit('0');
                        })),
                    _Key('=', kind: _Kind.equals, onTap: () => _press(_c.equals)),
                  ],
                ),
      ],
    );

    return Focus(
      focusNode: _typing,
      autofocus: widget.listenToKeyboard,
      onKeyEvent: _typed,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // The body of the machine — keys inside one panel rather than
          // floating on the page, because a panel is what a hand reaches for.
          // Left off inside a sheet, where the sheet is already that panel.
          if (widget.framed)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: theme.colorScheme.surface,
                borderRadius: BorderRadius.circular(22),
                border:
                    Border.all(color: theme.dividerColor.withValues(alpha: 0.5)),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.06),
                    blurRadius: 18,
                    offset: const Offset(0, 6),
                  ),
                ],
              ),
              child: keys,
            )
          else
            keys,

          if (widget.onUse != null) ...[
            const SizedBox(height: 12),
            SizedBox(
              height: 50,
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

          if (widget.framed) ...[
            const SizedBox(height: 10),
            Text(
              context.t('Hold GT to clear the running total'),
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// The panel above the keys.
///
/// Carries **M** and **GT** markers, because a figure sitting in memory that
/// nobody can see is a figure that gets used by accident on the next sum. The
/// strip they sit in keeps its height whether or not anything is in it — on the
/// machine on the counter the keys do not move, and a pad that shifts under the
/// thumb halfway through a column is a pad that gets the wrong digit.
class _Display extends StatelessWidget {
  const _Display({required this.engine});

  final CalculatorEngine engine;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: 20,
            child: Row(
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
          ),
          const SizedBox(height: 4),
          SizedBox(
            height: 52,
            child: FittedBox(
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
  const _Row({required this.children, this.last = false});

  final List<Widget> children;
  final bool last;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: last ? 0 : 8),
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
      // Set back from the digits, but only in weight — grey on grey reads as a
      // key that has been switched off, and these are the ones a shop uses most
      // after the numbers.
      _Kind.memory => (scheme.surfaceContainerHighest, scheme.onSurface),
      _Kind.function => (scheme.surfaceContainerHighest, scheme.onSurface),
      _Kind.digit => (scheme.surfaceContainerLowest, scheme.onSurface),
    };

    return Expanded(
      flex: flex,
      child: SizedBox(
        height: 54,
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
                        ? theme.textTheme.titleMedium
                        : theme.textTheme.titleLarge)
                    ?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w700,
                  fontSize: kind == _Kind.equals ? 26 : null,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
