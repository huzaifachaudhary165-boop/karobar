import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// A worked-out percentage, as it reaches a bill.
///
/// Found on the deployed site: a sale of one Rs 180 packet showed "Profit Rs 52
/// (28.888888888888886%)". The arithmetic was right and the bill looked broken,
/// which to the person holding it is the same thing.
void main() {
  group('a percentage that came out of a division', () {
    test('does not print to fifteen places', () {
      expect(percentText(52 / 180 * 100), '28.9');
    });

    test('a third is a third, not 33.33333333333333', () {
      expect(percentText(100 / 3), '33.3');
    });

    test('a round number stays round', () {
      expect(percentText(25), '25');
      expect(percentText(28.0), '28');
    });

    test('one decimal is kept where it says something', () {
      expect(percentText(17.5), '17.5');
    });

    test('and dropped where it does not', () {
      expect(percentText(17.04), '17');
    });

    test('a loss is still written as a number', () {
      expect(percentText(-12.345), '-12.3');
    });

    test('nothing is nothing', () {
      expect(percentText(0), '0');
    });
  });
}
