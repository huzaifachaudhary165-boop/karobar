import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/document_types.dart';
import 'package:karobar/data/models.dart';

/// What each trade document is, and what the form does about it.
///
/// These three properties have to agree with the server or the bill comes out
/// wrong: the wrong side of the trade prices a purchase at retail, a payment
/// field on an order collects money the ledger has nowhere to put, and a stock
/// flag that disagrees means the shelf figure drifts from the shelf.
void main() {
  group('sides of the trade', () {
    test('buying documents pick a supplier and price from cost', () {
      for (final doc in [
        DocumentType.purchase,
        DocumentType.purchaseOrder,
        DocumentType.purchaseReturn,
      ]) {
        expect(doc.isPurchase, isTrue, reason: '${doc.key} is a buying document');
      }
    });

    test('selling documents do not', () {
      for (final doc in [
        DocumentType.sale,
        DocumentType.saleOrder,
        DocumentType.quotation,
        DocumentType.proforma,
        DocumentType.deliveryChallan,
        DocumentType.saleReturn,
      ]) {
        expect(doc.isPurchase, isFalse, reason: '${doc.key} is a selling document');
      }
    });
  });

  group('money', () {
    test('only a transaction takes payment', () {
      expect(DocumentType.sale.takesPayment, isTrue);
      expect(DocumentType.purchase.takesPayment, isTrue);
      expect(DocumentType.saleReturn.takesPayment, isTrue);
      expect(DocumentType.purchaseReturn.takesPayment, isTrue);
    });

    test('no promise collects money', () {
      // Nobody pays against an order. The money arrives with the invoice it
      // becomes, and offering the field invites an entry with nowhere to go.
      for (final doc in [
        DocumentType.quotation,
        DocumentType.proforma,
        DocumentType.saleOrder,
        DocumentType.purchaseOrder,
        DocumentType.deliveryChallan,
      ]) {
        expect(doc.takesPayment, isFalse, reason: '${doc.key} must not take payment');
      }
    });
  });

  group('stock', () {
    test('ordering goods does not move them', () {
      expect(DocumentType.saleOrder.movesStock, isFalse);
      expect(DocumentType.purchaseOrder.movesStock, isFalse);
      expect(DocumentType.quotation.movesStock, isFalse);
      expect(DocumentType.proforma.movesStock, isFalse);
    });

    test('a delivery challan does, because the goods have left', () {
      expect(DocumentType.deliveryChallan.movesStock, isTrue);
    });

    test('every transaction moves stock', () {
      for (final doc in [
        DocumentType.sale,
        DocumentType.purchase,
        DocumentType.saleReturn,
        DocumentType.purchaseReturn,
      ]) {
        expect(doc.movesStock, isTrue, reason: '${doc.key} changes what is on the shelf');
      }
    });
  });

  group('who it is for', () {
    test('a quotation can be drafted without naming anyone', () {
      expect(DocumentType.quotation.needsParty, isFalse);
    });

    test('everything else needs a party', () {
      for (final doc in DocumentType.values.where((d) => d != DocumentType.quotation)) {
        expect(doc.needsParty, isTrue, reason: '${doc.key} is raised for someone');
      }
    });
  });

  group('looking one up', () {
    test('a known key resolves', () {
      expect(DocumentType.of('purchase_order'), DocumentType.purchaseOrder);
      expect(DocumentType.of('delivery_challan'), DocumentType.deliveryChallan);
    });

    test('an unknown key falls back to a sale rather than throwing', () {
      // This reaches here from a deep link or an older build's saved state, and
      // a crash on the documents tab is a far worse answer than showing sales.
      expect(DocumentType.of('nonsense'), DocumentType.sale);
      expect(DocumentType.of(null), DocumentType.sale);
      expect(DocumentType.of(''), DocumentType.sale);
    });

    test('every key is unique', () {
      final keys = DocumentType.values.map((d) => d.key).toList();
      expect(keys.toSet().length, keys.length);
    });

    test('the listed tabs are all real types', () {
      for (final doc in DocumentType.listed) {
        expect(DocumentType.of(doc.key), doc);
      }
    });
  });

  group('the convert menu is built from the server, not guessed', () {
    test('a document with nothing to become offers nothing', () {
      final invoice = Voucher.fromJson({
        'id': 'v1',
        'number': 'INV-0001',
        'voucher_type': 'sale',
        'status': 'unpaid',
        'voucher_date': '2026-08-01',
        'convertible_to': <String>[],
      });

      expect(invoice.canConvert, isFalse);
    });

    test('a purchase order offers exactly what the server allows', () {
      final order = Voucher.fromJson({
        'id': 'v2',
        'number': 'PO-0001',
        'voucher_type': 'purchase_order',
        'status': 'unpaid',
        'voucher_date': '2026-08-01',
        'convertible_to': ['purchase'],
      });

      expect(order.canConvert, isTrue);
      expect(order.convertibleTo, ['purchase']);
      expect(order.convertibleTo, isNot(contains('sale')),
          reason: 'billing your own supplier as a customer is the bug this prevents');
    });

    test('a missing field is an empty list, not a crash', () {
      final voucher = Voucher.fromJson({
        'id': 'v3',
        'number': 'INV-0002',
        'voucher_type': 'sale',
        'status': 'paid',
        'voucher_date': '2026-08-01',
      });

      expect(voucher.convertibleTo, isEmpty);
      expect(voucher.canConvert, isFalse);
    });

    test('a converted document is finished', () {
      final quote = Voucher.fromJson({
        'id': 'v4',
        'number': 'QTN-0001',
        'voucher_type': 'quotation',
        'status': 'converted',
        'voucher_date': '2026-08-01',
        'convertible_to': <String>[],
      });

      expect(quote.isConverted, isTrue);
      expect(quote.canConvert, isFalse);
    });
  });

  group('labels', () {
    test('every order document has a readable name', () {
      final voucher = Voucher.fromJson({
        'id': 'v5',
        'number': 'SO-0001',
        'voucher_type': 'sale_order',
        'status': 'unpaid',
        'voucher_date': '2026-08-01',
      });
      expect(voucher.typeLabel, 'Sale order');
    });

    test('an unrecognised type still reads as words, not an identifier', () {
      final voucher = Voucher.fromJson({
        'id': 'v6',
        'number': 'X-1',
        'voucher_type': 'some_new_thing',
        'status': 'unpaid',
        'voucher_date': '2026-08-01',
      });
      expect(voucher.typeLabel, 'some new thing');
    });
  });
}
