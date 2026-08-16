import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

/// Listens for a USB barcode gun anywhere on the screen.
///
/// A handheld scanner is not a camera. It registers as a keyboard, types the
/// digits of the barcode as fast as the machine will take them, and presses
/// Enter. That is why it works in a browser and on a desktop where the camera
/// plugin does not exist at all — and it is what a shop with a laptop at the
/// counter actually owns.
///
/// The whole problem is telling it apart from a person typing, because both
/// arrive as key events. Speed is the tell: a gun delivers a whole code in
/// tens of milliseconds, a person cannot. So keys that arrive faster than
/// [_humanGap] accumulate, Enter completes the code, and anything slower is
/// left alone for whatever field has focus.
///
/// Wrapped around a screen rather than tied to a text field: a shopkeeper
/// holding the gun does not first click into a box, and requiring that is how
/// a scanner ends up "not working".
class HandheldScannerListener extends StatefulWidget {
  const HandheldScannerListener({
    super.key,
    required this.child,
    required this.onScan,
    this.enabled = true,
    this.clock,
  });

  final Widget child;

  /// Fires with the finished code, once, when Enter arrives.
  final ValueChanged<String> onScan;

  /// Off while a sheet or dialog is taking input of its own.
  final bool enabled;

  /// Reads the time, so a test can decide what "fast" means.
  ///
  /// The whole behaviour is a speed judgement, and a widget test's clock does
  /// not move `DateTime.now`. Without this the only way to test the difference
  /// between a gun and a person is to sit through real delays, which makes the
  /// one thing worth being sure about the one thing nobody re-runs.
  final DateTime Function()? clock;

  @override
  State<HandheldScannerListener> createState() =>
      _HandheldScannerListenerState();
}

/// Longer than a gun's gap between characters, shorter than a person's.
///
/// Cheap scanners land around 5-15ms; a fast typist is above 80ms even in a
/// burst. 60 leaves room on both sides without either one crossing it.
const _humanGap = Duration(milliseconds: 60);

/// Shorter than this and it was somebody leaning on the keyboard, not a code.
/// Every real barcode symbology in a shop is longer.
const _shortestCode = 4;

class _HandheldScannerListenerState extends State<HandheldScannerListener> {
  final _buffer = StringBuffer();

  DateTime? _lastKey;
  Timer? _expiry;

  @override
  void initState() {
    super.initState();
    // Registered globally rather than on a focus node. A focus node only sees
    // keys while it or a child holds focus, and a shopkeeper pulls the trigger
    // while looking at the screen, not at a text field — which is precisely
    // how a scanner ends up "not working".
    HardwareKeyboard.instance.addHandler(_onKey);
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_onKey);
    _expiry?.cancel();
    super.dispose();
  }

  void _reset() {
    _buffer.clear();
    _lastKey = null;
    _expiry?.cancel();
    _expiry = null;
  }

  bool _onKey(KeyEvent event) {
    if (!widget.enabled || event is! KeyDownEvent) return false;

    final now = (widget.clock ?? DateTime.now)();
    final gap = _lastKey == null ? Duration.zero : now.difference(_lastKey!);
    _lastKey = now;

    // A pause means whatever came before was somebody typing, so it is not
    // part of a code and must not be glued to what comes next.
    if (gap > _humanGap) _buffer.clear();

    if (event.logicalKey == LogicalKeyboardKey.enter ||
        event.logicalKey == LogicalKeyboardKey.numpadEnter) {
      final code = _buffer.toString().trim();
      _reset();

      if (code.length < _shortestCode) return false;
      widget.onScan(code);
      // Swallowed, or the same Enter also submits whatever form is open.
      return true;
    }

    final char = event.character;
    if (char == null || char.isEmpty || char.codeUnitAt(0) < 0x20) return false;
    _buffer.write(char);

    // A gun that never sends Enter — some are configured that way — would
    // otherwise leave its digits sitting here to be glued onto the next scan.
    _expiry?.cancel();
    _expiry = Timer(const Duration(milliseconds: 300), _reset);

    // Not handled: a person typing into a field must still see their letters.
    // Only the completing Enter is taken.
    return false;
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
