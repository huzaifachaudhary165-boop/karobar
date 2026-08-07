import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// Repeating bills as the app reads them.
///
/// The run result matters most: it is what the dashboard shows after invoices
/// have gone out in the shop's name. A shopkeeper finding those bills later
/// with no idea where they came from is the worst version of this feature, so
/// "did anything happen" has to be answerable without ambiguity.
void main() {
  group('a schedule', () {
    test('parses with everything it carries', () {
      final bill = RecurringBill.fromJson({
        'id': 'r1',
        'name': 'Shop rent',
        'voucher_type': 'sale',
        'party_id': 'p1',
        'party_name': 'Ahmed Traders',
        'frequency': 'monthly',
        'interval': 1,
        'schedule_label': 'Every month',
        'starts_on': '2026-01-01',
        'next_run_on': '2026-09-01',
        'occurrences': 8,
        'total_billed': '118400.0000',
        'auto_create': true,
        'is_active': true,
        'is_due': false,
        'lines': [
          {'item_name': 'Sugar', 'qty': '2', 'rate': '7400.00'},
        ],
      });

      expect(bill.scheduleLabel, 'Every month');
      expect(bill.partyName, 'Ahmed Traders');
      expect(bill.occurrences, 8);
      expect(bill.totalBilled, 118400);
      expect(bill.isDue, isFalse);
    });

    test('works out what one run comes to', () {
      final bill = RecurringBill.fromJson({
        'id': 'r2',
        'name': 'Weekly supply',
        'starts_on': '2026-01-01',
        'next_run_on': '2026-01-08',
        'lines': [
          {'item_name': 'Sugar', 'qty': '2', 'rate': '7400.00'},
          {'item_name': 'Oil', 'qty': '3', 'rate': '2750.00'},
        ],
      });

      expect(bill.estimatedTotal, 14800 + 8250);
    });

    test('a schedule with no lines comes to nothing rather than crashing', () {
      final bill = RecurringBill.fromJson({
        'id': 'r3',
        'name': 'Empty',
        'starts_on': '2026-01-01',
        'next_run_on': '2026-01-08',
      });
      expect(bill.estimatedTotal, 0);
      expect(bill.lines, isEmpty);
    });

    test('a finished schedule says so', () {
      final bill = RecurringBill.fromJson({
        'id': 'r4',
        'name': 'Done',
        'starts_on': '2026-01-01',
        'next_run_on': '2026-06-01',
        'occurrences': 6,
        'max_occurrences': 6,
        'is_finished': true,
        'is_active': false,
      });

      expect(bill.isFinished, isTrue);
      expect(bill.isActive, isFalse);
    });

    test('a schedule that only reminds says so', () {
      final bill = RecurringBill.fromJson({
        'id': 'r5',
        'name': 'Check first',
        'starts_on': '2026-01-01',
        'next_run_on': '2026-02-01',
        'auto_create': false,
        'is_active': true,
      });
      expect(bill.autoCreate, isFalse);
    });

    test('a problem from the last run is carried through', () {
      final bill = RecurringBill.fromJson({
        'id': 'r6',
        'name': 'Forgotten',
        'starts_on': '2020-01-01',
        'next_run_on': '2020-01-01',
        'last_error': '400+ bills are owed on this schedule.',
      });
      expect(bill.lastError, contains('400+'));
    });
  });

  group('what a run did', () {
    test('nothing happening is unambiguous', () {
      const run = RecurringRun();
      expect(run.isQuiet, isTrue);
      expect(run.totalRaised, 0);
    });

    test('bills raised are counted and totalled', () {
      final run = RecurringRun.fromJson({
        'created': [
          {'voucher_id': 'v1', 'number': 'INV-0001', 'name': 'Rent', 'total': '14800.00'},
          {'voucher_id': 'v2', 'number': 'INV-0002', 'name': 'Supply', 'total': '8250.00'},
        ],
        'checked_on': '2026-08-07',
      });

      expect(run.isQuiet, isFalse);
      expect(run.created.length, 2);
      expect(run.totalRaised, 23050);
      expect(run.created.first.number, 'INV-0001');
    });

    test('a reminder alone is still something to show', () {
      final run = RecurringRun.fromJson({
        'created': <Map<String, dynamic>>[],
        'reminders': [
          {'id': 'r1', 'name': 'Check first', 'due_count': 1},
        ],
        'checked_on': '2026-08-07',
      });

      expect(run.isQuiet, isFalse);
      expect(run.created, isEmpty);
      expect(run.reminders.single['name'], 'Check first');
    });

    test('a problem alone is still something to show', () {
      final run = RecurringRun.fromJson({
        'problems': [
          {'id': 'r1', 'name': 'Forgotten', 'reason': 'Check the dates'},
        ],
        'checked_on': '2026-08-07',
      });

      expect(run.isQuiet, isFalse);
      expect(run.problems.single['reason'], 'Check the dates');
    });

    test('an empty response parses without throwing', () {
      final run = RecurringRun.fromJson({'checked_on': '2026-08-07'});
      expect(run.isQuiet, isTrue);
    });
  });
}
