import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// The report catalogue as the app reads it.
///
/// The point of it is that a report added on the server appears in the app
/// without an app release, so the parsing has to survive entries the app has
/// never seen — including ones it cannot reach yet.
void main() {
  group('a report entry', () {
    test('one with a screen of its own is reachable', () {
      final entry = ReportEntry.fromJson({
        'key': 'cheques',
        'name': 'Cheques',
        'about': 'To deposit and to clear',
        'screen': 'cheques',
      });

      expect(entry.screen, 'cheques');
      expect(entry.endpoint, isNull);
      expect(entry.isReachable, isTrue);
    });

    test('one with only an endpoint is reachable through the viewer', () {
      final entry = ReportEntry.fromJson({
        'key': 'dead-stock',
        'name': 'Dead stock',
        'about': 'Goods not selling',
        'endpoint': '/reports/dead-stock',
      });

      expect(entry.endpoint, '/reports/dead-stock');
      expect(entry.isReachable, isTrue);
    });

    test('one the app cannot reach says so rather than pretending', () {
      // A future report whose screen has not been written yet. Showing it as
      // tappable and doing nothing is the worse of the two failures.
      final entry = ReportEntry.fromJson({
        'key': 'something-new',
        'name': 'Something new',
        'about': 'Added on the server',
      });

      expect(entry.isReachable, isFalse);
    });

    test('a missing field does not crash the list', () {
      final entry = ReportEntry.fromJson({'key': 'x'});
      expect(entry.name, '');
      expect(entry.about, '');
      expect(entry.isReachable, isFalse);
    });
  });

  group('groups', () {
    test('a group carries its reports', () {
      final group = ReportGroup.fromJson({
        'title': 'Stock',
        'reports': [
          {'key': 'dead-stock', 'name': 'Dead stock', 'about': 'Not selling',
           'endpoint': '/reports/dead-stock'},
          {'key': 'stock-ageing', 'name': 'Stock ageing', 'about': 'How long',
           'endpoint': '/reports/stock-ageing'},
        ],
      });

      expect(group.title, 'Stock');
      expect(group.reports.length, 2);
      expect(group.reports.every((r) => r.isReachable), isTrue);
    });

    test('an empty group parses without throwing', () {
      final group = ReportGroup.fromJson({'title': 'Empty'});
      expect(group.reports, isEmpty);
    });

    test('every key in a catalogue is distinct', () {
      final groups = [
        ReportGroup.fromJson({
          'title': 'A',
          'reports': [
            {'key': 'one', 'name': 'One', 'about': ''},
            {'key': 'two', 'name': 'Two', 'about': ''},
          ],
        }),
        ReportGroup.fromJson({
          'title': 'B',
          'reports': [
            {'key': 'three', 'name': 'Three', 'about': ''},
          ],
        }),
      ];

      final keys = [
        for (final group in groups)
          for (final report in group.reports) report.key,
      ];
      expect(keys.toSet().length, keys.length);
    });
  });
}
