import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/trade_maths.dart';

/// The arithmetic a wholesaler does all day.
///
/// Every one of these is a sum somebody currently does on a phone calculator
/// and gets wrong in a particular, expensive way. The tests are written around
/// those particular ways.
void main() {
  group('margin and markup are not the same number', () {
    // The classic. Buy at 100, sell at 125: that is 25% markup and 20% margin.
    // Somebody quoted "20%" who works it out as markup sells at 120 and is
    // short on every single unit.
    const m = Margin(cost: 100, price: 125);

    test('markup is against what it cost', () {
      expect(m.markupPercent, closeTo(25, 0.001));
    });

    test('margin is against what it sold for', () {
      expect(m.marginPercent, closeTo(20, 0.001));
    });

    test('both are given, so nobody has to remember which they were quoted', () {
      expect(m.markupPercent, isNot(closeTo(m.marginPercent, 0.001)));
    });

    test('profit is the same figure either way', () {
      expect(m.profit, 25);
    });
  });

  group('working back to a price', () {
    test('a 20% margin on a 100 cost is 125, not 120', () {
      expect(Margin.priceForMargin(100, 20), closeTo(125, 0.001));
    });

    test('a 20% markup on a 100 cost is 120', () {
      expect(Margin.priceForMarkup(100, 20), closeTo(120, 0.001));
    });

    test('100% margin is impossible rather than infinite', () {
      // The price would have to be infinite. Somebody typing 100 means markup,
      // and an absurd figure on screen is worse than being told why.
      expect(Margin.priceForMargin(100, 100), isNull);
      expect(Margin.priceForMargin(100, 150), isNull);
    });

    test('and the cost that a price and margin imply', () {
      expect(Margin.costForMargin(125, 20), closeTo(100, 0.001));
    });

    test('selling under cost is reported as a loss', () {
      const under = Margin(cost: 100, price: 80);
      expect(under.isLoss, isTrue);
      expect(under.profit, -20);
    });
  });

  group('discounts come off one after another', () {
    test('"10 and 5" is not 15', () {
      // 1000 → 900 → 855. Reading it as 15% gives 850, and the difference is
      // somebody's money.
      const d = Discount(1000, [10, 5]);
      expect(d.finalAmount, closeTo(855, 0.001));
      expect(d.saved, closeTo(145, 0.001));
    });

    test('and it says what the chain comes to as one figure', () {
      const d = Discount(1000, [10, 5]);
      expect(d.effectivePercent, closeTo(14.5, 0.001));
    });

    test('one discount behaves the obvious way', () {
      expect(const Discount(1000, [10]).finalAmount, closeTo(900, 0.001));
    });

    test('no discount changes nothing', () {
      expect(const Discount(1000, []).finalAmount, 1000);
    });
  });

  group('tax on top, and tax dug back out', () {
    test('adding it', () {
      const t = Tax(amount: 1000, rate: 17);
      expect(t.tax, closeTo(170, 0.001));
      expect(t.total, closeTo(1170, 0.001));
    });

    test('removing it is a division, not a subtraction', () {
      // The half people get wrong: 1170 less 17% is 971.10, which is not the
      // answer. It is 1170 ÷ 1.17.
      const t = Tax(amount: 1170, rate: 17, inclusive: true);
      expect(t.base, closeTo(1000, 0.001));
      expect(t.tax, closeTo(170, 0.001));
      expect(t.total, closeTo(1170, 0.001));
    });

    test('the wrong way round would give 971, and does not', () {
      const t = Tax(amount: 1170, rate: 17, inclusive: true);
      expect(t.base, isNot(closeTo(971.1, 1)));
    });

    test('zero tax leaves the figure alone', () {
      const t = Tax(amount: 500, rate: 0);
      expect(t.total, 500);
      expect(t.tax, 0);
    });
  });

  group('the units a shop here actually buys in', () {
    UnitFamily family(String name) =>
        tradeUnits.firstWhere((f) => f.name == name);

    test('a maund is 40 kilos', () {
      // The Pakistani maund. A general converter gives the older 37.32 kg
      // figure and would be wrong by a tenth on every sack.
      expect(family('Weight').convert(1, from: 'Maund', to: 'Kg'),
          closeTo(40, 0.001));
    });

    test('and forty seer make one', () {
      expect(family('Weight').convert(40, from: 'Seer', to: 'Maund'),
          closeTo(1, 0.001));
    });

    test('a ton is twenty-five maund', () {
      expect(family('Weight').convert(1, from: 'Ton', to: 'Maund'),
          closeTo(25, 0.001));
    });

    test('a thaan is twenty gaz', () {
      expect(family('Length & cloth').convert(1, from: 'Thaan (20 gaz)', to: 'Gaz / Yard'),
          closeTo(20, 0.01));
    });

    test('a gross is a dozen dozen', () {
      expect(family('Count').convert(1, from: 'Gross', to: 'Dozen'),
          closeTo(12, 0.001));
    });

    test('a kanal is twenty marla', () {
      expect(family('Area & volume').convert(1, from: 'Kanal', to: 'Marla'),
          closeTo(20, 0.001));
    });

    test('converting to itself changes nothing', () {
      for (final f in tradeUnits) {
        final unit = f.units.keys.first;
        expect(f.convert(7, from: unit, to: unit), closeTo(7, 0.0001),
            reason: f.name);
      }
    });

    test('a unit that is not in the family gives nothing, not nonsense', () {
      // A maund is not convertible to a gaz, and an answer would only be a
      // way to get a wrong one.
      expect(family('Weight').convert(1, from: 'Maund', to: 'Gaz / Yard'), 0);
    });

    test('every family has a base worth exactly one', () {
      for (final f in tradeUnits) {
        expect(f.units.values, contains(1.0), reason: '${f.name} has no base');
      }
    });
  });

  group('the small questions with no key for them', () {
    test('what one unit costs when the price was for many', () {
      // "1200 a maund" is not a price anybody bills at — the bill says kilos.
      expect(pricePerUnit(totalPrice: 1200, quantity: 40), closeTo(30, 0.001));
    });

    test('dividing by nothing gives nothing rather than infinity', () {
      expect(pricePerUnit(totalPrice: 1200, quantity: 0), 0);
    });

    test('what share one customer was of the day', () {
      expect(percentOf(2500, 10000), closeTo(25, 0.001));
    });

    test('how much something went up', () {
      expect(changePercent(100, 125), closeTo(25, 0.001));
      expect(changePercent(100, 75), closeTo(-25, 0.001));
    });

    test('a change from nothing is not a division by zero', () {
      expect(changePercent(0, 500), 0);
    });
  });
}
