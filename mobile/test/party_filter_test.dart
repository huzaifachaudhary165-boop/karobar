import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/providers.dart';

/// The party list's chip row mixes two different ideas.
///
/// All, Customer, Supplier describe a *kind* of party. To collect and To pay
/// describe a *balance*. Sending a balance word as `party_type` made the server
/// reject the whole request, so tapping either of those two chips replaced the
/// list with "Could not load parties — Some fields are invalid".
///
/// The values here must stay in step with the `party_type` pattern in
/// `backend/app/api/v1/endpoints/parties.py`, which is
/// `^(customer|supplier|both|all)$`.
void main() {
  group('chips that name a kind of party', () {
    test('are sent as party_type', () {
      expect(partyTypeForFilter('customer'), 'customer');
      expect(partyTypeForFilter('supplier'), 'supplier');
      expect(partyTypeForFilter('both'), 'both');
    });
  });

  group('chips that describe a balance', () {
    test('are never sent as party_type', () {
      // The reported bug, in one line each.
      expect(partyTypeForFilter('receivable'), isNull);
      expect(partyTypeForFilter('payable'), isNull);
    });
  });

  test('"all" means no filter rather than a party type called all', () {
    expect(partyTypeForFilter('all'), isNull);
  });

  test('an unknown chip is dropped rather than sent and rejected', () {
    // A new chip added to the screen must fail safe: show everything, not
    // break the screen.
    expect(partyTypeForFilter('vip'), isNull);
    expect(partyTypeForFilter(''), isNull);
  });

  test('every accepted value is one the server will take', () {
    // Mirrors the backend pattern exactly.
    const serverAccepts = {'customer', 'supplier', 'both', 'all'};
    for (final value in partyTypeFilters) {
      expect(serverAccepts, contains(value),
          reason: '$value would be rejected with 422 by the parties endpoint');
    }
  });

  test('the chips the screen actually shows are all handled', () {
    // Straight from parties_screen.dart.
    const chips = ['all', 'customer', 'supplier', 'receivable', 'payable'];
    for (final chip in chips) {
      final sent = partyTypeForFilter(chip);
      expect(sent == null || partyTypeFilters.contains(sent), isTrue,
          reason: 'chip "$chip" would send an unacceptable party_type');
    }
  });
}
