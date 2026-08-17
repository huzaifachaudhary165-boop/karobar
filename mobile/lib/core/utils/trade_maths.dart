/// The arithmetic a wholesaler does all day, kept away from any screen.
///
/// A keypad is not what most of this is. "What do I sell at for 20% margin",
/// "what is 10 and then 5 off", "how many kilos in three maund" — each is a
/// form with two knowns and one answer, and doing them on a plain calculator
/// means remembering which way round the formula goes. Getting margin and
/// markup the wrong way round is the classic one, and it is worth real money.
library;

/// Cost, selling price and what is made between them.
///
/// Margin and markup are the two numbers people mean by "percent", and they
/// are not the same: buy at 100, sell at 125, and that is 25% markup but 20%
/// margin. A shopkeeper told "20%" who works it out as markup sells at 120 and
/// is short on every single unit. Both are given, always, so nobody has to
/// remember which one they were quoted.
class Margin {
  const Margin({
    required this.cost,
    required this.price,
  });

  final num cost;
  final num price;

  num get profit => price - cost;

  /// Profit as a share of what it sold for. What accountants mean.
  double get marginPercent =>
      price == 0 ? 0 : (profit / price * 100).toDouble();

  /// Profit as a share of what it cost. What "put 25% on it" means.
  double get markupPercent =>
      cost == 0 ? 0 : (profit / cost * 100).toDouble();

  bool get isLoss => profit < 0;

  /// What to sell at for a given **margin** — a share of the selling price.
  ///
  /// Impossible at 100% or more: the price would have to be infinite, and
  /// somebody who types 100 means markup. Returns null rather than an absurd
  /// figure, so the screen can say why.
  static num? priceForMargin(num cost, num marginPercent) {
    if (marginPercent >= 100) return null;
    return cost / (1 - marginPercent / 100);
  }

  /// What to sell at for a given **markup** — a share of the cost.
  static num priceForMarkup(num cost, num markupPercent) =>
      cost * (1 + markupPercent / 100);

  /// What it must have cost to sell at [price] on this margin.
  static num? costForMargin(num price, num marginPercent) {
    if (marginPercent >= 100) return null;
    return price * (1 - marginPercent / 100);
  }
}

/// One or more discounts, taken in order.
///
/// A wholesaler is quoted "10 and 5" and it does not mean 15. Each comes off
/// what is left after the last, so 1000 becomes 900 and then 855. Reading it
/// as 15% gives 850 and the difference is somebody's money.
class Discount {
  const Discount(this.amount, this.percents);

  final num amount;
  final List<num> percents;

  num get finalAmount {
    var left = amount;
    for (final percent in percents) {
      left -= left * percent / 100;
    }
    return left;
  }

  num get saved => amount - finalAmount;

  /// What the chain comes to as a single figure, for writing on the bill.
  double get effectivePercent =>
      amount == 0 ? 0 : (saved / amount * 100).toDouble();
}

/// Tax added on top, or dug back out of a price that already includes it.
///
/// Pulling tax out is the half people get wrong: 1170 at 17% is not 1170 less
/// 17%. It is 1170 ÷ 1.17, and the difference on a day's billing is not small.
class Tax {
  const Tax({required this.amount, required this.rate, this.inclusive = false});

  final num amount;
  final num rate;

  /// True when [amount] already has the tax in it.
  final bool inclusive;

  num get base => inclusive ? amount / (1 + rate / 100) : amount;
  num get tax => inclusive ? amount - base : amount * rate / 100;
  num get total => inclusive ? amount : amount + tax;
}

/// A unit a Pakistani shop actually buys and sells in, and what it comes to.
///
/// Kept as ratios to one base per family rather than a general converter: a
/// maund is not convertible to a gaz, and offering it would only be a way to
/// get a wrong answer.
class UnitFamily {
  const UnitFamily({
    required this.name,
    required this.baseLabel,
    required this.units,
  });

  final String name;

  /// What everything in this family is expressed in.
  final String baseLabel;

  /// How much of the base each one is worth.
  final Map<String, double> units;

  num convert(num value, {required String from, required String to}) {
    final a = units[from];
    final b = units[to];
    if (a == null || b == null || b == 0) return 0;
    return value * a / b;
  }
}

/// The families a shop here works in.
///
/// The Pakistani maund is 40 kg — the older 37.32 kg one has not been used in
/// trade for a long time — and a seer is one fortieth of it. These are the
/// figures a grain market quotes; getting them from a general converter would
/// give the Indian values and be wrong by a tenth.
const tradeUnits = <UnitFamily>[
  UnitFamily(
    name: 'Weight',
    baseLabel: 'Kg',
    units: {
      'Kg': 1,
      'Gram': 0.001,
      'Seer': 1.0,          // 1/40 of a maund
      'Maund': 40,
      'Quintal': 100,
      'Ton': 1000,
      'Bori (50kg)': 50,
      'Bori (100kg)': 100,
    },
  ),
  UnitFamily(
    name: 'Length & cloth',
    baseLabel: 'Metre',
    units: {
      'Metre': 1,
      'Foot': 0.3048,
      'Inch': 0.0254,
      'Gaz / Yard': 0.9144,
      'Thaan (20 gaz)': 18.288,
    },
  ),
  UnitFamily(
    name: 'Count',
    baseLabel: 'Piece',
    units: {
      'Piece': 1,
      'Dozen': 12,
      'Gross': 144,
      'Pair': 2,
      'Carton (24)': 24,
      'Carton (48)': 48,
    },
  ),
  UnitFamily(
    name: 'Area & volume',
    baseLabel: 'Sqft',
    units: {
      'Sqft': 1,
      'Sqm': 10.7639,
      'Marla': 272.25,
      'Kanal': 5445,
    },
  ),
];

/// What one unit costs when the price was quoted for a bigger one.
///
/// "1200 a maund" is not a price anybody bills at — the bill says kilos. Doing
/// it by hand is where a decimal goes missing.
num pricePerUnit({
  required num totalPrice,
  required num quantity,
}) =>
    quantity == 0 ? 0 : totalPrice / quantity;

/// What X is as a percentage of Y.
///
/// "How much of today's sale was that one customer" — a question with a
/// two-second answer that nobody has a key for.
double percentOf(num part, num whole) =>
    whole == 0 ? 0 : (part / whole * 100).toDouble();

/// How much something changed, in percent, from [before] to [after].
double changePercent(num before, num after) =>
    before == 0 ? 0 : ((after - before) / before * 100).toDouble();
