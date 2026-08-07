import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// Price lists, offers and quotes as the app reads them.
///
/// The one that matters is [QuoteLine.reason]: it is what the bill screen puts
/// under a line so the shopkeeper can account for the rate out loud. A total
/// nobody can explain to the customer in front of them is worse than no
/// discount at all.
void main() {
  group('price lists', () {
    test('a discount list reads as a discount', () {
      final list = PriceList.fromJson({
        'id': 'p1',
        'name': 'Wholesale',
        'adjust_percent': '-8.0000',
        'base_price': 'sale',
        'item_count': 12,
      });

      expect(list.isDiscount, isTrue);
      expect(list.ruleLabel, '8% off sale price');
      expect(list.itemCount, 12);
    });

    test('a markup list reads as a markup', () {
      final list = PriceList.fromJson({
        'id': 'p2',
        'name': 'Retail plus',
        'adjust_percent': '12.0000',
        'base_price': 'purchase',
      });

      expect(list.isDiscount, isFalse);
      expect(list.ruleLabel, '12% on purchase price');
    });

    test('a list with no rule says it uses item prices', () {
      final list = PriceList.fromJson({'id': 'p3', 'name': 'Standard'});
      expect(list.ruleLabel, 'Item prices');
    });

    test('a list that only changes the base price says which', () {
      final list = PriceList.fromJson({
        'id': 'p4', 'name': 'At MRP', 'base_price': 'mrp',
      });
      expect(list.ruleLabel, 'At mrp price');
    });
  });

  group('offers', () {
    test('a percentage offer reads the way a customer would be told', () {
      final scheme = DiscountScheme.fromJson({
        'id': 's1',
        'name': 'Eid offer',
        'discount_type': 'percent',
        'discount_value': '10.0000',
        'is_running': true,
      });

      expect(scheme.isPercent, isTrue);
      expect(scheme.valueLabel, '10% off');
      expect(scheme.isRunning, isTrue);
    });

    test('a flat offer reads in rupees', () {
      final scheme = DiscountScheme.fromJson({
        'id': 's2',
        'name': 'Rs 200 off',
        'discount_type': 'amount',
        'discount_value': '200.0000',
      });

      expect(scheme.isPercent, isFalse);
      expect(scheme.valueLabel, 'Rs 200 off');
    });

    test('a fractional percentage keeps its decimal', () {
      final scheme = DiscountScheme.fromJson({
        'id': 's3', 'name': 'Half', 'discount_value': '2.5000',
      });
      expect(scheme.valueLabel, '2.5% off');
    });

    test('an expired offer parses as not running', () {
      final scheme = DiscountScheme.fromJson({
        'id': 's4',
        'name': 'Ended',
        'discount_value': '10',
        'ends_on': '2026-01-01',
        'is_running': false,
      });

      expect(scheme.isRunning, isFalse);
      expect(scheme.endsOn, isNotNull);
    });
  });

  group('what the bill screen says about a rate', () {
    test('an ordinary rate needs no explanation', () {
      final quote = QuoteLine.fromJson({
        'item_id': 'i1',
        'qty': '1',
        'rate': '7400.00',
        'line_total': '7400.00',
        'discount': '0',
        'net': '7400.00',
        'source': 'item',
      });

      expect(quote.isSpecial, isFalse);
      expect(quote.reason, isNull);
    });

    test('a price list rate names the list', () {
      final quote = QuoteLine.fromJson({
        'item_id': 'i1',
        'rate': '6808.00',
        'line_total': '6808.00',
        'discount': '0',
        'net': '6808.00',
        'source': 'list_rule',
        'price_list_name': 'Wholesale',
      });

      expect(quote.isSpecial, isTrue);
      expect(quote.reason, 'Wholesale');
    });

    test('a discount names the offer, not the list', () {
      final quote = QuoteLine.fromJson({
        'item_id': 'i1',
        'rate': '7400.00',
        'line_total': '7400.00',
        'discount': '740.00',
        'net': '6660.00',
        'source': 'list_rule',
        'price_list_name': 'Wholesale',
        'scheme_name': 'Eid 10%',
      });

      expect(quote.reason, 'Eid 10%',
          reason: 'the offer is what the customer is being given');
    });

    test('a held rate says so above everything else', () {
      // The shopkeeper tried to go below the floor. That is the thing they
      // need told, not which list the rate came from.
      final quote = QuoteLine.fromJson({
        'item_id': 'i1',
        'rate': '7200.00',
        'line_total': '7200.00',
        'discount': '100.00',
        'net': '7100.00',
        'source': 'list_rule',
        'price_list_name': 'Too deep',
        'scheme_name': 'Clearance',
        'held_at_minimum': true,
      });

      expect(quote.reason, 'Held at the minimum price');
    });

    test('a zero discount does not count as an explanation', () {
      final quote = QuoteLine.fromJson({
        'item_id': 'i1',
        'rate': '7400.00',
        'line_total': '7400.00',
        'discount': '0',
        'net': '7400.00',
        'source': 'item',
        'scheme_name': 'Some offer',
      });

      expect(quote.reason, isNull, reason: 'nothing was actually taken off');
    });

    test('money arrives as strings and still parses', () {
      final quote = QuoteLine.fromJson({
        'item_id': 'i1',
        'qty': '3.0000',
        'rate': '2750.0000',
        'line_total': '8250.0000',
        'discount': '412.5000',
        'net': '7837.5000',
        'source': 'list_entry',
      });

      expect(quote.qty, 3);
      expect(quote.rate, 2750);
      expect(quote.discount, 412.5);
      expect(quote.lineTotal - quote.discount, quote.net);
    });
  });
}
