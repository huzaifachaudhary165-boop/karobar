import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// Tax, loyalty and manufacturing as the app reads them.
void main() {
  group('the tax return', () {
    test('a shop that has not turned it on says so', () {
      final figures = TaxReturn.fromJson({'enabled': false});
      expect(figures.enabled, isFalse);
      expect(figures.totalSales, 0);
    });

    test('the figures parse from their string amounts', () {
      final figures = TaxReturn.fromJson({
        'enabled': true,
        'registered_sales': '10000.00',
        'unregistered_sales': '5000.00',
        'total_sales': '15000.00',
        'output_tax': '2700.00',
        'further_tax': '150.00',
        'input_tax': '1000.00',
        'unclaimable_input_tax': '450.00',
        'net_payable': '1850.00',
        'carried_forward': '0',
        'sale_count': 12,
      });

      expect(figures.registeredSales, 10000);
      expect(figures.furtherTax, 150);
      expect(figures.unclaimableInputTax, 450);
      expect(figures.owesNothing, isFalse);
    });

    test('input above output reads as carried forward, not as owing nothing by luck', () {
      final figures = TaxReturn.fromJson({
        'enabled': true,
        'net_payable': '0',
        'carried_forward': '20000.00',
      });

      expect(figures.owesNothing, isTrue);
      expect(figures.carriedForward, 20000);
    });
  });

  group('the loyalty scheme', () {
    test('the earn rate reads the way a shopkeeper would say it', () {
      final program = LoyaltyProgram.fromJson({
        'id': 'p1',
        'earn_rate': '0.0100',
        'point_value': '1.00',
        'cost_percent': '1.00',
      });

      expect(program.earnLabel, 'One point per Rs 100');
      expect(program.costPercent, 1);
    });

    test('a different rate reads correctly too', () {
      final program = LoyaltyProgram.fromJson({
        'id': 'p2', 'earn_rate': '0.0200', 'point_value': '1.00',
      });
      expect(program.earnLabel, 'One point per Rs 50');
    });

    test('a scheme earning nothing says so rather than dividing by zero', () {
      final program = LoyaltyProgram.fromJson({'id': 'p3', 'earn_rate': '0'});
      expect(program.earnLabel, 'No points');
    });

    test('an entry reads the way a customer would be told', () {
      final entry = LoyaltyEntry.fromJson({
        'id': 'e1',
        'kind': 'redeemed',
        'points': -60,
        'balance_after': 40,
        'value': '60.00',
        'created_at': '2026-08-07T10:00:00Z',
      });

      expect(entry.label, 'Used');
      expect(entry.isEarning, isFalse);
      expect(entry.balanceAfter, 40);
    });

    test('a cancelled bill is named as such, not as an adjustment', () {
      final entry = LoyaltyEntry.fromJson({
        'id': 'e2', 'kind': 'reversed', 'points': -100,
        'created_at': '2026-08-07T10:00:00Z',
      });
      expect(entry.label, 'Bill cancelled');
    });

    test('a quote with nothing to offer says so', () {
      const empty = LoyaltyQuote();
      expect(empty.hasSomethingToOffer, isFalse);

      final some = LoyaltyQuote.fromJson({
        'enabled': true, 'balance': 100, 'redeemable': 100, 'value': '100.00',
      });
      expect(some.hasSomethingToOffer, isTrue);
    });

    test('a scheme switched on with no points to spend offers nothing', () {
      final quote = LoyaltyQuote.fromJson({
        'enabled': true, 'balance': 0, 'redeemable': 0,
      });
      expect(quote.hasSomethingToOffer, isFalse);
    });
  });

  group('recipes', () {
    test('a recipe carries what it costs and what can be made', () {
      final recipe = Recipe.fromJson({
        'id': 'r1',
        'name': 'Rusk tray',
        'item_id': 'i1',
        'item_name': 'Rusk',
        'output_qty': '40.0000',
        'unit_cost': '32.05',
        'batch_cost': '1282.00',
        'can_make': '480.0000',
        'components': [
          {'item_id': 'm1', 'item_name': 'Flour', 'qty': '2.0000', 'rate': '120.00'},
        ],
      });

      expect(recipe.unitCost, 32.05);
      expect(recipe.canMake, 480);
      expect(recipe.hasMaterials, isTrue);
      expect(recipe.components.single.itemName, 'Flour');
    });

    test('a recipe with no materials on hand says so', () {
      final recipe = Recipe.fromJson({
        'id': 'r2', 'name': 'Nothing', 'item_id': 'i1', 'can_make': '0',
      });
      expect(recipe.hasMaterials, isFalse);
    });

    test('a costing names what is short before anything is committed', () {
      final costing = RecipeCosting.fromJson({
        'making': '2000',
        'material_cost': '42000.00',
        'total_cost': '42000.00',
        'unit_cost': '21.00',
        'can_make_now': false,
        'shortages': [
          {
            'item_id': 'm2', 'item_name': 'Sugar',
            'needed': '50.0000', 'available': '20.0000', 'short_by': '30.0000',
          },
        ],
      });

      expect(costing.canMakeNow, isFalse);
      expect(costing.shortages.single.itemName, 'Sugar');
      expect(costing.shortages.single.shortBy, 30);
    });

    test('a run records what it cost at the time', () {
      final run = ProductionRun.fromJson({
        'id': 'run1',
        'number': 'MFG-0001',
        'item_name': 'Rusk',
        'run_date': '2026-08-07',
        'qty': '40.0000',
        'total_cost': '1282.00',
        'unit_cost': '32.05',
      });

      expect(run.number, 'MFG-0001');
      expect(run.unitCost, 32.05);
      expect(run.qty, 40);
    });
  });
}
