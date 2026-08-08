import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// Whether an item is followed piece by piece.
///
/// The bill screen asks "which batch?" and "which handset?" off these flags
/// alone. Read wrong, a chemist's stock silently stops being followed by
/// expiry, or a kiryana shop is asked which batch of sugar it is selling.
void main() {
  Item parse(Map<String, dynamic> extra) => Item.fromJson({
        'id': 'i1',
        'name': 'Panadol',
        'unit_label': 'Strip',
        ...extra,
      });

  group('reading the flags off the server', () {
    test('an item that says nothing is not tracked', () {
      final item = parse({});
      expect(item.trackBatches, isFalse);
      expect(item.trackExpiry, isFalse);
      expect(item.trackSerial, isFalse);
    });

    test('each flag is read on its own', () {
      expect(parse({'track_batches': true}).trackBatches, isTrue);
      expect(parse({'track_expiry': true}).trackExpiry, isTrue);
      expect(parse({'track_serial': true}).trackSerial, isTrue);
    });

    test('one flag being on does not turn the others on', () {
      final item = parse({'track_serial': true});
      expect(item.trackSerial, isTrue);
      expect(item.trackBatches, isFalse);
      expect(item.trackExpiry, isFalse);
    });

    test('a missing flag is off, not an error', () {
      // The list endpoint and the detail endpoint are different shapes, and a
      // bill built from a response missing these must still open.
      expect(() => parse({'track_batches': null}), returnsNormally);
      expect(parse({'track_batches': null}).trackBatches, isFalse);
    });
  });

  group('what the bill screen asks', () {
    test('sugar is asked nothing', () {
      final item = parse({});
      expect(item.needsBatchPicked, isFalse);
      expect(item.needsSerialPicked, isFalse);
    });

    test('a medicine tracked by expiry is asked which batch', () {
      // Expiry belongs to a batch, so tracking expiry alone still has to ask.
      expect(parse({'track_expiry': true}).needsBatchPicked, isTrue);
    });

    test('a batch-tracked item is asked which batch even with no expiry', () {
      expect(parse({'track_batches': true}).needsBatchPicked, isTrue);
    });

    test('a handset is asked which piece, not which batch', () {
      final item = parse({'track_serial': true});
      expect(item.needsSerialPicked, isTrue);
      expect(item.needsBatchPicked, isFalse);
    });

    test('an item can be followed both ways at once', () {
      final item = parse({'track_batches': true, 'track_serial': true});
      expect(item.needsBatchPicked, isTrue);
      expect(item.needsSerialPicked, isTrue);
    });
  });
}
