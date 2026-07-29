import 'package:intl/intl.dart';

/// Money and date formatting for South Asian shops.
abstract final class Fmt {
  /// Indian/Pakistani grouping: 12,34,567.89 — not the Western 1,234,567.89.
  static String money(num? value, {String symbol = 'Rs ', bool decimals = true}) {
    final amount = value ?? 0;
    final negative = amount < 0;
    final absolute = amount.abs();

    final text = decimals ? absolute.toStringAsFixed(2) : absolute.round().toString();
    final parts = text.split('.');
    final grouped = _groupIndian(parts.first);
    final joined = parts.length > 1 ? '$grouped.${parts[1]}' : grouped;

    return '${negative ? '-' : ''}$symbol$joined';
  }

  /// Compact for dashboard tiles: 1.2L, 45K, 3.4Cr.
  static String compactMoney(num? value, {String symbol = 'Rs '}) {
    final amount = (value ?? 0).abs();
    final sign = (value ?? 0) < 0 ? '-' : '';
    if (amount >= 10000000) return '$sign$symbol${(amount / 10000000).toStringAsFixed(2)}Cr';
    if (amount >= 100000) return '$sign$symbol${(amount / 100000).toStringAsFixed(2)}L';
    if (amount >= 1000) return '$sign$symbol${(amount / 1000).toStringAsFixed(1)}K';
    return money(value, symbol: symbol, decimals: false);
  }

  static String _groupIndian(String digits) {
    if (digits.length <= 3) return digits;
    final tail = digits.substring(digits.length - 3);
    var head = digits.substring(0, digits.length - 3);
    final groups = <String>[];
    while (head.length > 2) {
      groups.insert(0, head.substring(head.length - 2));
      head = head.substring(0, head.length - 2);
    }
    if (head.isNotEmpty) groups.insert(0, head);
    return '${groups.join(',')},$tail';
  }

  /// Trims a trailing `.0000` so "5 Bag" doesn't read as "5.0000 Bag".
  static String qty(num? value) {
    final amount = value ?? 0;
    if (amount == amount.roundToDouble()) return amount.round().toString();
    return amount.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  }

  static String percent(num? value, {int decimals = 1}) =>
      '${(value ?? 0).toStringAsFixed(decimals)}%';

  // ── dates ──────────────────────────────────────────────────────
  static final _day = DateFormat('d MMM yyyy');
  static final _dayShort = DateFormat('d MMM');
  static final _time = DateFormat('h:mm a');
  static final _monthYear = DateFormat('MMMM yyyy');
  static final _iso = DateFormat('yyyy-MM-dd');

  static String date(DateTime? value) => value == null ? '—' : _day.format(value);
  static String dateShort(DateTime? value) => value == null ? '—' : _dayShort.format(value);
  static String time(DateTime? value) => value == null ? '—' : _time.format(value);
  static String monthYear(DateTime value) => _monthYear.format(value);
  static String iso(DateTime value) => _iso.format(value);

  static String dateTime(DateTime? value) =>
      value == null ? '—' : '${_dayShort.format(value)} · ${_time.format(value)}';

  /// "Today", "Yesterday", "3 days ago", then a plain date.
  static String relative(DateTime? value) {
    if (value == null) return '—';
    final today = DateTime.now();
    final days = DateTime(today.year, today.month, today.day)
        .difference(DateTime(value.year, value.month, value.day))
        .inDays;

    return switch (days) {
      0 => 'Today',
      1 => 'Yesterday',
      -1 => 'Tomorrow',
      > 1 && < 7 => '$days days ago',
      < -1 && > -7 => 'In ${-days} days',
      _ => _day.format(value),
    };
  }

  static String overdueLabel(int days) => switch (days) {
        <= 0 => 'Due',
        1 => '1 day overdue',
        _ => '$days days overdue',
      };

  static DateTime? parseDate(String? value) =>
      (value == null || value.isEmpty) ? null : DateTime.tryParse(value);

  // ── text ───────────────────────────────────────────────────────
  static String initials(String name, {int count = 2}) {
    final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    return parts.take(count).map((p) => p[0].toUpperCase()).join();
  }

  static String truncate(String value, int length) =>
      value.length <= length ? value : '${value.substring(0, length - 1)}…';

  static String titleCase(String value) => value
      .replaceAll('_', ' ')
      .split(' ')
      .map((word) => word.isEmpty ? word : '${word[0].toUpperCase()}${word.substring(1)}')
      .join(' ');
}
