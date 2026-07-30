import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// The shop list is read from the server, written to disk, and read back on the
/// next launch. If a field is lost in that round trip the app decides the user
/// has no shop — and then walks them into registration to create a second one,
/// splitting their data across two businesses.
void main() {
  test('a shop survives being written to disk and read back', () {
    const original = Business(
      id: '7507afa4-f16c-48f3-b589-3615e7f0223a',
      name: 'Deploy Check Store',
      businessType: 'wholesale',
      currencySymbol: 'Rs',
      currency: 'PKR',
      logoUrl: 'https://example.test/logo.png',
      role: 'owner',
      plan: 'free',
    );

    final revived = Business.fromJson(original.toJson());

    expect(revived.id, original.id);
    expect(revived.name, original.name);
    expect(revived.businessType, original.businessType);
    expect(revived.currency, original.currency);
    expect(revived.currencySymbol, original.currencySymbol);
    expect(revived.logoUrl, original.logoUrl);
    // Role decides what the user is allowed to do; losing it silently would
    // hand a salesman the owner's permissions or vice versa.
    expect(revived.role, original.role);
    expect(revived.plan, original.plan);
  });

  test('the id survives, because that is what the active shop is matched on', () {
    const shop = Business(id: 'abc-123', name: 'Corner Shop');
    expect(Business.fromJson(shop.toJson()).id, 'abc-123');
  });

  test('a server payload with nulls does not lose the id', () {
    final revived = Business.fromJson({
      'id': 'xyz-789',
      'name': 'Minimal Shop',
      'logo_url': null,
      'role': null,
    });

    expect(revived.id, 'xyz-789');
    expect(revived.name, 'Minimal Shop');
    // And the defaults must be usable, not empty strings on a bill.
    expect(revived.currency, 'PKR');
    expect(revived.symbol.trim(), 'Rs');
  });
}
