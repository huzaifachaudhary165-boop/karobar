import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// Parsing the new stock and money responses.
///
/// Money and quantities arrive as JSON **strings** — the server holds them as
/// Decimal and Pydantic serialises a Decimal as a string so nothing is lost in
/// transit. Reading one with `as num` throws, and that is exactly what took the
/// Items tab down once already. Every new model is checked against the shape
/// the API actually sends, string amounts and all.
void main() {
  group('locations', () {
    test('a location parses with its string money', () {
      final godown = Godown.fromJson({
        'id': 'g1',
        'name': 'Main Store',
        'address': 'Shop 4, Anarkali',
        'is_default': true,
        'item_count': 37,
        'stock_value': '482350.5000',
      });

      expect(godown.name, 'Main Store');
      expect(godown.isDefault, isTrue);
      expect(godown.itemCount, 37);
      expect(godown.stockValue, 482350.5);
    });

    test('a location with nothing in it does not crash', () {
      final godown = Godown.fromJson({'id': 'g2', 'name': 'Godown'});
      expect(godown.stockValue, 0);
      expect(godown.itemCount, 0);
      expect(godown.address, isNull);
    });

    test('per-location quantities parse', () {
      final row = ItemGodownRow.fromJson({
        'godown_id': 'g1',
        'godown_name': 'Branch 2',
        'is_default': false,
        'qty': '124.0000',
      });
      expect(row.qty, 124);
      expect(row.godownName, 'Branch 2');
    });
  });

  group('batches', () {
    test('an expiring batch carries its item and its days', () {
      final row = ExpiringBatch.fromJson({
        'batch': {
          'id': 'b1',
          'item_id': 'i1',
          'batch_number': 'PN-4471',
          'expiry_date': '2026-09-01',
          'qty': '48.0000',
          'is_expired': false,
          'days_to_expiry': 25,
        },
        'item_id': 'i1',
        'item_name': 'Panadol 500mg',
        'unit_label': 'Strip',
        'value': '8640.0000',
      });

      expect(row.itemName, 'Panadol 500mg');
      expect(row.batch.batchNumber, 'PN-4471');
      expect(row.batch.qty, 48);
      expect(row.daysToExpiry, 25);
      expect(row.isExpired, isFalse);
      expect(row.value, 8640);
    });

    test('an already-expired batch reports negative days', () {
      final batch = ItemBatch.fromJson({
        'id': 'b2',
        'item_id': 'i1',
        'batch_number': 'OLD-1',
        'is_expired': true,
        'days_to_expiry': -30,
        'qty': '8.0000',
      });

      expect(batch.isExpired, isTrue);
      expect(batch.daysToExpiry, -30);
      expect(batch.isExpiringSoon, isFalse,
          reason: 'already expired is not "expiring soon" — it is a loss');
    });

    test('a batch inside the month is flagged as expiring soon', () {
      final batch = ItemBatch.fromJson({
        'id': 'b3',
        'item_id': 'i1',
        'batch_number': 'SOON',
        'is_expired': false,
        'days_to_expiry': 12,
      });
      expect(batch.isExpiringSoon, isTrue);
    });

    test('a batch with no expiry date at all is neither', () {
      final batch = ItemBatch.fromJson({
        'id': 'b4',
        'item_id': 'i1',
        'batch_number': 'NO-DATE',
      });
      expect(batch.expiryDate, isNull);
      expect(batch.isExpired, isFalse);
      expect(batch.isExpiringSoon, isFalse);
    });
  });

  group('serials', () {
    test('an in-stock unit is available', () {
      final serial = ItemSerial.fromJson({
        'id': 's1',
        'item_id': 'i1',
        'serial_number': 'IMEI-0099',
        'status': 'in_stock',
        'purchase_price': '55000.0000',
        'in_warranty': true,
        'warranty_until': '2027-01-01',
      });

      expect(serial.isAvailable, isTrue);
      expect(serial.purchasePrice, 55000);
      expect(serial.inWarranty, isTrue);
    });

    test('a sold unit is not available', () {
      final serial = ItemSerial.fromJson({
        'id': 's2',
        'item_id': 'i1',
        'serial_number': 'IMEI-0100',
        'status': 'sold',
      });
      expect(serial.isAvailable, isFalse);
    });

    test('a returned unit is sellable again', () {
      final serial = ItemSerial.fromJson({
        'id': 's3',
        'item_id': 'i1',
        'serial_number': 'IMEI-0101',
        'status': 'returned',
      });
      expect(serial.isAvailable, isTrue);
    });

    test('duplicates come back alongside what was added', () {
      final result = SerialAddResult.fromJson({
        'added': [
          {'id': 's4', 'item_id': 'i1', 'serial_number': 'A-2'},
        ],
        'duplicates': ['A-1'],
        'added_count': 1,
        'available_count': 3,
      });

      expect(result.addedCount, 1);
      expect(result.duplicates, ['A-1']);
      expect(result.added.single.serialNumber, 'A-2');
    });
  });

  group('accounts and transfers', () {
    test('a bank account parses its string balance', () {
      final account = BankAccount.fromJson({
        'id': 'a1',
        'name': 'Meezan Current',
        'account_type': 'bank',
        'bank_name': 'Meezan Bank',
        'balance': '230000.0000',
        'is_default': false,
      });

      expect(account.balance, 230000);
      expect(account.isCash, isFalse);
    });

    test('a cash drawer is recognised as cash', () {
      final account =
          BankAccount.fromJson({'id': 'a2', 'name': 'Counter', 'account_type': 'cash'});
      expect(account.isCash, isTrue);
    });

    test('a transfer keeps the fee separate from the amount', () {
      final transfer = AccountTransfer.fromJson({
        'id': 't1',
        'from_account_id': 'a1',
        'to_account_id': 'a2',
        'from_account_name': 'UBL',
        'to_account_name': 'Easypaisa',
        'amount': '25000.0000',
        'charges': '150.0000',
        'total_debited': '25150.0000',
        'transfer_date': '2026-08-01',
      });

      expect(transfer.amount, 25000);
      expect(transfer.charges, 150);
      expect(transfer.totalDebited, 25150,
          reason: 'the fee leaves the sender and arrives nowhere');
    });
  });

  group('cheques', () {
    test('an unsettled cheque is still open', () {
      final cheque = Cheque.fromJson({
        'id': 'c1',
        'number': 'RCP-0001',
        'direction': 'in',
        'payment_date': '2026-08-01',
        'amount': '45000.0000',
        'cheque_status': 'pending',
        'days_until_due': 10,
      });

      expect(cheque.isIncoming, isTrue);
      expect(cheque.isSettled, isFalse);
      expect(cheque.amount, 45000);
    });

    test('a bounced cheque counts as settled, not as still waiting', () {
      final cheque = Cheque.fromJson({
        'id': 'c2',
        'number': 'RCP-0002',
        'direction': 'in',
        'payment_date': '2026-08-01',
        'cheque_status': 'bounced',
      });
      expect(cheque.isSettled, isTrue);
    });

    test('an overdue cheque reports negative days', () {
      final cheque = Cheque.fromJson({
        'id': 'c3',
        'number': 'RCP-0003',
        'direction': 'out',
        'payment_date': '2026-07-01',
        'is_overdue': true,
        'days_until_due': -4,
      });

      expect(cheque.isOverdue, isTrue);
      expect(cheque.daysUntilDue, -4);
      expect(cheque.isIncoming, isFalse);
    });
  });

  group('loans', () {
    test('a loan parses its string money and reports progress', () {
      final loan = Loan.fromJson({
        'id': 'l1',
        'lender_name': 'Meezan Bank',
        'start_date': '2026-01-01',
        'loan_type': 'business',
        'principal': '500000.0000',
        'interest_rate': '12.0000',
        'interest_type': 'reducing',
        'tenure_months': 24,
        'emi_amount': '23536.7400',
        'outstanding_principal': '375000.0000',
        'principal_paid': '125000.0000',
        'interest_paid': '18000.0000',
        'total_paid': '143000.0000',
        'status': 'active',
        'instalments_paid': 6,
        'instalments_left': 18,
        'next_due_date': '2026-08-01',
      });

      expect(loan.emiAmount, 23536.74);
      expect(loan.progress, closeTo(0.25, 0.001));
      expect(loan.isClosed, isFalse);
      expect(loan.isInterestFree, isFalse);
      expect(loan.instalmentsLeft, 18);
    });

    test('an interest-free loan is recognised as such', () {
      final loan = Loan.fromJson({
        'id': 'l2',
        'lender_name': 'Chacha Rashid',
        'start_date': '2026-01-01',
        'loan_type': 'personal',
        'principal': '120000.0000',
        'interest_rate': '0.0000',
        'interest_type': 'none',
      });
      expect(loan.isInterestFree, isTrue);
    });

    test('a settled loan reads as fully repaid', () {
      final loan = Loan.fromJson({
        'id': 'l3',
        'lender_name': 'Ammi',
        'start_date': '2026-01-01',
        'principal': '50000.0000',
        'principal_paid': '50000.0000',
        'outstanding_principal': '0.0000',
        'status': 'closed',
      });

      expect(loan.isClosed, isTrue);
      expect(loan.progress, 1.0);
    });

    test('progress never exceeds one, whatever the figures say', () {
      final loan = Loan.fromJson({
        'id': 'l4',
        'lender_name': 'Odd',
        'start_date': '2026-01-01',
        'principal': '1000.0000',
        'principal_paid': '1200.0000',
      });
      expect(loan.progress, 1.0);
    });

    test('a repayment carries both halves of the split', () {
      final payment = LoanPayment.fromJson({
        'id': 'p1',
        'loan_id': 'l1',
        'payment_date': '2026-02-01',
        'amount': '10000.0000',
        'principal_component': '9000.0000',
        'interest_component': '1000.0000',
        'balance_after': '91000.0000',
        'instalment_number': 1,
      });

      expect(payment.principalComponent + payment.interestComponent, payment.amount);
      expect(payment.balanceAfter, 91000);
    });

    test('a schedule row parses', () {
      final row = LoanInstalment.fromJson({
        'number': 1,
        'due_date': '2026-02-15',
        'amount': '23536.7400',
        'principal': '18536.7400',
        'interest': '5000.0000',
        'balance_after': '481463.2600',
      });

      expect(row.number, 1);
      expect(row.principal + row.interest, row.amount);
    });
  });
}
