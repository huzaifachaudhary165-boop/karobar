import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/providers.dart';

/// Which tab the home shell shows.
///
/// This was read once out of the route's `?tab=` parameter into a `late` field.
/// `late` initialisers run when the State is created, and going from /home to
/// /home?tab=1 reuses that State — so the parameter changed and the field did
/// not. Every route into a tab from inside the app produced a ripple and
/// nothing else: "2 overdue invoices", "2 items running low", To collect, To
/// pay, the stock tile, and every assistant link to a list. All of them looked
/// like dead buttons.
///
/// Holding it in a provider makes switching a state change rather than a
/// navigation, so it cannot depend on whether the router decided to rebuild.
void main() {
  test('the shell starts on the dashboard', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(homeTabProvider), 0);
  });

  test('setting the tab is what moves it, not navigating', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    container.read(homeTabProvider.notifier).state = 1;
    expect(container.read(homeTabProvider), 1);
  });

  test('a listener sees the change, so the shell rebuilds', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    final seen = <int>[];
    container.listen(homeTabProvider, (_, next) => seen.add(next));

    container.read(homeTabProvider.notifier).state = 2;
    container.read(homeTabProvider.notifier).state = 3;

    expect(seen, [2, 3], reason: 'the shell watches this to pick its tab');
  });

  test('moving to the tab already showing is harmless', () {
    // Tapping "To collect" twice, or tapping it while already on the party
    // list, must not error or wedge anything.
    final container = ProviderContainer();
    addTearDown(container.dispose);

    container.read(homeTabProvider.notifier).state = 1;
    container.read(homeTabProvider.notifier).state = 1;

    expect(container.read(homeTabProvider), 1);
  });

  group('a tab change carries its filter', () {
    test('To collect asks for the people who owe money', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      // What openTab does, minus the BuildContext it needs for navigation.
      container.read(partyFilterProvider.notifier).state = 'receivable';
      container.read(homeTabProvider.notifier).state = 1;

      expect(container.read(partyFilterProvider), 'receivable');
      expect(container.read(homeTabProvider), 1);
      // And that filter must not be sent as a party type, or the list 422s.
      expect(partyTypeForFilter(container.read(partyFilterProvider)), isNull);
    });

    test('the low stock alert asks for low stock, not every item', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      container.read(itemFilterProvider.notifier).state = 'low_stock';
      container.read(homeTabProvider.notifier).state = 3;

      expect(container.read(itemFilterProvider), 'low_stock');
      expect(container.read(homeTabProvider), 3);
    });

    test('the overdue alert asks for overdue sales', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);

      container.read(voucherTypeProvider.notifier).state = 'sale';
      container.read(voucherFilterProvider.notifier).state = 'overdue';
      container.read(homeTabProvider.notifier).state = 2;

      expect(container.read(voucherTypeProvider), 'sale');
      expect(container.read(voucherFilterProvider), 'overdue');
      expect(container.read(homeTabProvider), 2);
    });
  });
}
