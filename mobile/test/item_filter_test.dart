import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/providers.dart';

/// Which items each chip on the item list asks for.
///
/// An item on old bills cannot be deleted, so the app tells the shopkeeper to
/// retire it instead. That advice is only worth giving if retiring actually
/// takes the item off the list and off the picker on the next bill.
///
/// Getting this backwards fails in both directions: hide every item the shop
/// sells, or quietly put discontinued stock back in front of a customer.
void main() {
  test('the everyday chips ask for what the shop still sells', () {
    expect(itemActiveForFilter('all'), isTrue);
    expect(itemActiveForFilter('low_stock'), isTrue);
  });

  test('only the retired chip asks for retired items', () {
    expect(itemActiveForFilter('retired'), isFalse);
  });

  test('a chip nobody has written yet still shows live items', () {
    // A new chip added to the screen must fail safe. Showing the shop's own
    // stock is safe; showing what it stopped selling is not.
    expect(itemActiveForFilter('expiring'), isTrue);
    expect(itemActiveForFilter(''), isTrue);
  });

  test('every chip the screen shows is handled', () {
    // Straight from items_screen.dart.
    for (final chip in ['all', 'low_stock', 'retired']) {
      expect(itemActiveForFilter(chip), isNotNull,
          reason: 'chip "$chip" would ask for both at once');
    }
  });
}
