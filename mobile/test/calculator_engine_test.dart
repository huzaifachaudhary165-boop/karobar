import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/calculator_engine.dart';

/// The calculator that sits on a shop counter.
///
/// Modelled on the desktop machine people here already own. A shopkeeper has
/// muscle memory for those keys, and one that answers differently is one they
/// stop trusting after the first sum they check by hand — so these are written
/// around what the machine on the counter does, not what a phone does.
void main() {
  late CalculatorEngine c;

  setUp(() => c = CalculatorEngine());

  void press(String keys) {
    for (final key in keys.split(' ')) {
      switch (key) {
        case '+' || '−' || '×' || '÷':
          c.operate(key);
        case '=':
          c.equals();
        case '%':
          c.percent();
        default:
          c.digit(key);
      }
    }
  }

  group('the four operations', () {
    test('adds', () {
      press('1 2 + 8 =');
      expect(c.entry, '20');
    });

    test('subtracts', () {
      press('5 0 − 8 =');
      expect(c.entry, '42');
    });

    test('multiplies', () {
      press('1 2 × 8 =');
      expect(c.entry, '96');
    });

    test('divides', () {
      press('9 6 ÷ 8 =');
      expect(c.entry, '12');
    });

    test('chains without equals between steps', () {
      // Totalling a delivery note is one operator after another.
      press('1 0 + 2 0 + 5 =');
      expect(c.entry, '35');
    });

    test('dividing by nothing leaves the number alone', () {
      press('8 0 ÷ 0 =');
      expect(c.entry, '80');
    });
  });

  group('percent, the way the counter machine does it', () {
    test('taking ten off a thousand takes off a hundred', () {
      // A scientific calculator gives 0.1 here. The machine on the counter
      // does not, and this follows the counter.
      press('1 0 0 0 − 1 0 %');
      c.equals();
      expect(c.entry, '900');
    });

    test('putting tax on top', () {
      press('1 0 0 0 + 1 7 %');
      c.equals();
      expect(c.entry, '1170');
    });

    test('on its own it divides by a hundred', () {
      press('5 0 %');
      expect(c.entry, '0.5');
    });
  });

  group('the keys that are not on a phone', () {
    test('square root', () {
      press('1 4 4');
      c.squareRoot();
      expect(c.entry, '12');
    });

    test('a negative has no root, so the number is left alone', () {
      // "NaN" on a counter is worse than doing nothing.
      press('9');
      c.toggleSign();
      c.squareRoot();
      expect(c.entry, '-9');
    });

    test('sign flips both ways', () {
      press('5 0');
      c.toggleSign();
      expect(c.entry, '-50');
      c.toggleSign();
      expect(c.entry, '50');
    });

    test('flipping the sign of nothing does nothing', () {
      c.toggleSign();
      expect(c.entry, '0');
    });
  });

  group('memory', () {
    test('adds to and recalls', () {
      press('5 0 0');
      c.memoryAdd();
      press('2 0 0');
      c.memoryAdd();
      c.memoryRecall();

      expect(c.entry, '700');
      expect(c.hasMemory, isTrue);
    });

    test('subtracts from it', () {
      press('5 0 0');
      c.memoryAdd();
      press('2 0 0');
      c.memorySubtract();
      c.memoryRecall();

      expect(c.entry, '300');
    });

    test('a half-finished sum is settled before it is stored', () {
      // M+ after "12 × 8" must store 96, not the 8 still on the display.
      press('1 2 × 8');
      c.memoryAdd();
      c.memoryRecall();

      expect(c.entry, '96');
    });

    test('clearing empties it', () {
      press('5 0 0');
      c.memoryAdd();
      c.memoryClear();

      expect(c.hasMemory, isFalse);
      c.memoryRecall();
      expect(c.entry, '0');
    });
  });

  group('grand total', () {
    test('adds up every answer', () {
      // A wholesaler totals thirty lines by pressing equals thirty times and
      // then GT, rather than holding a running sum in their head.
      press('1 0 × 5 =');   // 50
      press('2 0 × 3 =');   // 60
      press('1 0 0 + 4 0 ='); // 140
      c.showGrandTotal();

      expect(c.entry, '250');
    });

    test('nothing added up yet is zero, not an error', () {
      c.showGrandTotal();
      expect(c.entry, '0');
    });

    test('it can be cleared without touching memory', () {
      press('1 0 + 1 0 =');
      press('5 0 0');
      c.memoryAdd();
      c.clearGrandTotal();

      expect(c.hasGrandTotal, isFalse);
      expect(c.hasMemory, isTrue);
    });
  });

  group('fixing a slip', () {
    test('backspace removes the last digit only', () {
      press('1 2 3');
      c.backspace();
      expect(c.entry, '12');
    });

    test('backspacing to nothing gives zero, not an empty display', () {
      press('7');
      c.backspace();
      expect(c.entry, '0');
    });

    test('clear entry keeps the sum in progress', () {
      press('1 0 0 +');
      press('9 9');
      c.clearEntry();
      press('5 0');
      c.equals();

      expect(c.entry, '150');
    });

    test('all clear drops the sum but keeps memory and the total', () {
      press('1 0 + 1 0 =');
      press('5 0 0');
      c.memoryAdd();
      press('9 9 9 +');
      c.allClear();

      expect(c.entry, '0');
      expect(c.hasMemory, isTrue, reason: 'memory has its own key');
      expect(c.hasGrandTotal, isTrue, reason: 'so does the grand total');
    });

    test('a second decimal point is ignored', () {
      press('1 . 5 . 5');
      expect(c.entry, '1.55');
    });
  });

  group('what the display says', () {
    test('a sum in progress is visible before the second number', () {
      press('1 2 +');
      expect(c.display, '12 +');
    });

    test('and with it', () {
      press('1 2 + 8');
      expect(c.display, '12 + 8');
    });

    test('the finished sum is kept so it can be checked', () {
      press('1 2 × 8 =');
      expect(c.lastSum, '12 × 8 =');
      expect(c.display, '96');
    });
  });

  group('the shape of the numbers', () {
    test('a whole number has no trailing point', () {
      press('1 0 ÷ 2 =');
      expect(c.entry, '5');
    });

    test('a fraction keeps only the digits that matter', () {
      press('1 0 ÷ 4 =');
      expect(c.entry, '2.5');
    });

    test('a long entry stops rather than running off the display', () {
      // Rupees, not physics. Past this nobody typed it on purpose.
      press('9 9 9 9 9 9 9 9 9 9 9 9 9 9 9 9');
      expect(c.entry.length, lessThanOrEqualTo(12));
    });

    test('a third of something is not written in exponent form', () {
      press('1 ÷ 3 =');
      expect(c.entry, isNot(contains('e')));
    });
  });
}
