/// The workings of the calculator that sits on a shop counter.
///
/// Modelled on the desktop machine people here already own — the Casio MJ-120D
/// and the dozen clones of it. That matters more than it sounds: a shopkeeper
/// has muscle memory for those keys, and a calculator that answers differently
/// is one they stop trusting after the first sum they check by hand.
///
/// Kept apart from any screen so the arithmetic can be tested on its own. Every
/// method returns nothing and mutates state, the way pressing a key does.
class CalculatorEngine {
  /// What the display shows.
  String entry = '0';

  /// The left-hand side of a sum in progress, and which sum it is.
  double? _pending;
  String? _operator;

  /// True when the next digit starts a new number instead of extending this.
  bool _fresh = true;

  /// What was in memory. Shown as **M** on the display, because a figure
  /// sitting in memory that nobody can see is a figure that gets used by
  /// accident on the next sum.
  double memory = 0;

  /// Grand total: every `=` result added up.
  ///
  /// The key nobody outside a shop uses and everybody in one does — a
  /// wholesaler totals thirty lines by pressing equals thirty times and then
  /// GT, rather than keeping a running sum in their head.
  double grandTotal = 0;

  /// The last completed sum, kept above the answer so it can be checked.
  String? lastSum;

  double get value => double.tryParse(entry) ?? 0;
  bool get hasMemory => memory != 0;
  bool get hasGrandTotal => grandTotal != 0;

  /// What is on the display right now, including a sum in progress.
  String get display {
    if (_operator == null) return entry;
    return '${_trim(_pending ?? 0)} $_operator${_fresh ? '' : ' $entry'}';
  }

  // ── keys ────────────────────────────────────────────────────────
  void digit(String d) {
    if (_fresh) {
      entry = d == '.' ? '0.' : d;
      _fresh = false;
      return;
    }
    if (d == '.' && entry.contains('.')) return;
    if (entry == '0' && d != '.') {
      entry = d;
      return;
    }
    // A shop's figures are rupees, not physics. Beyond this the display cannot
    // show it and nobody typed it on purpose.
    if (entry.replaceAll('.', '').replaceAll('-', '').length >= 12) return;
    entry += d;
  }

  void operate(String op) {
    if (_pending != null && _operator != null && !_fresh) {
      final result = _apply(_pending!, value, _operator!);
      lastSum = '${_trim(_pending!)} $_operator ${_trim(value)}';
      _pending = result;
      entry = _trim(result);
    } else {
      _pending = value;
    }
    _operator = op;
    _fresh = true;
  }

  /// Finishes the sum and adds the answer to the grand total.
  void equals() {
    if (_pending == null || _operator == null) return;
    final result = _apply(_pending!, value, _operator!);
    lastSum = '${_trim(_pending!)} $_operator ${_trim(value)} =';
    entry = _trim(result);
    grandTotal += result;
    _pending = null;
    _operator = null;
    _fresh = true;
  }

  /// Percent, meaning what a shop means by it.
  ///
  /// With a sum waiting it is a share of the left-hand side, so "1000 − 10 %"
  /// takes off 100. A scientific calculator gives 0.1 there, and the desktop
  /// machine on the counter does not — this follows the counter.
  void percent() {
    if (_pending != null && _operator != null) {
      entry = _trim(_pending! * value / 100);
    } else {
      entry = _trim(value / 100);
    }
    _fresh = false;
  }

  /// The square root key every one of these machines has.
  ///
  /// A negative has no root, and showing "NaN" to a shopkeeper is worse than
  /// leaving their number alone.
  void squareRoot() {
    if (value < 0) return;
    entry = _trim(_sqrt(value));
    _fresh = false;
  }

  void toggleSign() {
    if (value == 0) return;
    entry = entry.startsWith('-') ? entry.substring(1) : '-$entry';
    _fresh = false;
  }

  /// Removes the last digit. The key people reach for on a slip, rather than
  /// clearing the whole entry and typing it again.
  void backspace() {
    if (_fresh || entry.length <= 1 || (entry.length == 2 && entry.startsWith('-'))) {
      entry = '0';
      _fresh = true;
      return;
    }
    entry = entry.substring(0, entry.length - 1);
  }

  /// Clears what is being typed, keeping the sum in progress.
  void clearEntry() {
    entry = '0';
    _fresh = true;
  }

  /// Clears everything on the display. Memory and the grand total survive,
  /// which is what AC does on the machine — they have their own keys.
  void allClear() {
    entry = '0';
    _pending = null;
    _operator = null;
    _fresh = true;
    lastSum = null;
  }

  // ── memory ──────────────────────────────────────────────────────
  void memoryAdd() {
    _settle();
    memory += value;
    _fresh = true;
  }

  void memorySubtract() {
    _settle();
    memory -= value;
    _fresh = true;
  }

  /// Recalls what is in memory onto the display.
  void memoryRecall() {
    entry = _trim(memory);
    _fresh = false;
  }

  void memoryClear() => memory = 0;

  // ── grand total ─────────────────────────────────────────────────
  /// Shows the running total of every answer so far.
  void showGrandTotal() {
    entry = _trim(grandTotal);
    _pending = null;
    _operator = null;
    _fresh = true;
  }

  void clearGrandTotal() {
    grandTotal = 0;
    entry = '0';
    _fresh = true;
  }

  // ── inside ──────────────────────────────────────────────────────
  /// Finishes any sum in progress, so M+ after "12 × 8" stores 96 rather than
  /// the 8 still on the display.
  void _settle() {
    if (_pending != null && _operator != null && !_fresh) equals();
  }

  double _apply(double a, double b, String op) => switch (op) {
        '+' => a + b,
        '−' => a - b,
        '×' => a * b,
        // Dividing by nothing is a slip, not an answer. Infinity on a rate is
        // worse than the number they started from.
        '÷' => b == 0 ? a : a / b,
        _ => b,
      };

  static double _sqrt(double v) {
    // Newton's method: dart:math would do, but keeping this file free of
    // imports means it can be read as plain arithmetic.
    if (v == 0) return 0;
    var guess = v;
    for (var i = 0; i < 40; i++) {
      guess = (guess + v / guess) / 2;
    }
    return guess;
  }

  /// A number the way a shop writes it: no trailing zeros, and no exponent.
  static String _trim(double v) {
    if (v == v.roundToDouble() && v.abs() < 1e15) {
      return v.toStringAsFixed(0);
    }
    var text = v.toStringAsFixed(6);
    while (text.contains('.') && (text.endsWith('0') || text.endsWith('.'))) {
      text = text.substring(0, text.length - 1);
    }
    return text;
  }

  static String format(double v) => _trim(v);
}
