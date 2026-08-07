/// Riverpod wiring: infrastructure singletons, session state and the
/// async providers each screen watches.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/auth/google_auth.dart';
import 'core/network/api_client.dart';
import 'core/storage/token_store.dart';
import 'data/local/app_database.dart';
import 'data/models.dart';
import 'data/repositories.dart';
import 'data/sync_controller.dart';

// ── infrastructure ───────────────────────────────────────────────
/// Overridden in `main()` once SharedPreferences has loaded.
final tokenStoreProvider = Provider<TokenStore>(
  (ref) => throw UnimplementedError('tokenStoreProvider must be overridden in main()'),
);

/// Overridden in `main()`; tests inject `AppDatabase.memory()`.
final appDatabaseProvider = Provider<AppDatabase>(
  (ref) => throw UnimplementedError('appDatabaseProvider must be overridden in main()'),
);

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(
    ref.watch(tokenStoreProvider),
    cache: ref.watch(appDatabaseProvider),
  );
  // A dead refresh token means the session is over — drop back to signed-out.
  final subscription = client.onSessionExpired.listen((_) {
    ref.read(sessionProvider.notifier).forceSignOut();
  });
  ref.onDispose(() {
    subscription.cancel();
    client.dispose();
  });
  return client;
});

// ── repositories ─────────────────────────────────────────────────
final authRepositoryProvider = Provider(
  (ref) => AuthRepository(ref.watch(apiClientProvider), ref.watch(tokenStoreProvider)),
);
final partyRepositoryProvider = Provider((ref) => PartyRepository(ref.watch(apiClientProvider)));
final itemRepositoryProvider = Provider((ref) => ItemRepository(ref.watch(apiClientProvider)));
final voucherRepositoryProvider =
    Provider((ref) => VoucherRepository(ref.watch(apiClientProvider)));
final paymentRepositoryProvider =
    Provider((ref) => PaymentRepository(ref.watch(apiClientProvider)));
final expenseRepositoryProvider =
    Provider((ref) => ExpenseRepository(ref.watch(apiClientProvider)));
final reportRepositoryProvider =
    Provider((ref) => ReportRepository(ref.watch(apiClientProvider)));
final aiRepositoryProvider = Provider((ref) => AiRepository(ref.watch(apiClientProvider)));
final syncRepositoryProvider = Provider((ref) => SyncRepository(ref.watch(apiClientProvider)));
final notificationRepositoryProvider =
    Provider((ref) => NotificationRepository(ref.watch(apiClientProvider)));
final businessRepositoryProvider =
    Provider((ref) => BusinessRepository(ref.watch(apiClientProvider)));
final dataRepositoryProvider =
    Provider((ref) => DataRepository(ref.watch(apiClientProvider)));
final stockRepositoryProvider =
    Provider((ref) => StockRepository(ref.watch(apiClientProvider)));
final financeRepositoryProvider =
    Provider((ref) => FinanceRepository(ref.watch(apiClientProvider)));
final pricingRepositoryProvider =
    Provider((ref) => PricingRepository(ref.watch(apiClientProvider)));
final recurringRepositoryProvider =
    Provider((ref) => RecurringRepository(ref.watch(apiClientProvider)));

// ── offline queue ────────────────────────────────────────────────
/// Long-lived: it listens to connectivity for the whole session and flushes the
/// outbox the moment a connection comes back.
final syncControllerProvider = ChangeNotifierProvider<SyncController>((ref) {
  return SyncController(
    db: ref.watch(appDatabaseProvider),
    repository: ref.watch(syncRepositoryProvider),
    store: ref.watch(tokenStoreProvider),
  );
});

final syncStateProvider = Provider<SyncState>(
  (ref) => ref.watch(syncControllerProvider).state,
);

// ── session ──────────────────────────────────────────────────────
enum AuthStatus { unknown, signedOut, signedIn }

class SessionState {
  const SessionState({
    this.status = AuthStatus.unknown,
    this.user,
    this.business,
    this.businesses = const [],
    this.permissions = const {},
  });

  final AuthStatus status;
  final AppUser? user;
  final Business? business;
  final List<Business> businesses;
  final Set<String> permissions;

  bool get isSignedIn => status == AuthStatus.signedIn && business != null;
  bool get needsBusiness => status == AuthStatus.signedIn && business == null;
  String get symbol => business?.symbol ?? 'Rs ';

  /// An empty permission set means "not loaded yet" — allow rather than block.
  bool can(String permission) => permissions.isEmpty || permissions.contains(permission);

  SessionState copyWith({
    AuthStatus? status,
    AppUser? user,
    Business? business,
    List<Business>? businesses,
    Set<String>? permissions,
  }) =>
      SessionState(
        status: status ?? this.status,
        user: user ?? this.user,
        business: business ?? this.business,
        businesses: businesses ?? this.businesses,
        permissions: permissions ?? this.permissions,
      );
}

class SessionNotifier extends StateNotifier<SessionState> {
  SessionNotifier(this._ref) : super(const SessionState()) {
    _restore();
  }

  final Ref _ref;

  TokenStore get _store => _ref.read(tokenStoreProvider);
  AuthRepository get _auth => _ref.read(authRepositoryProvider);

  /// Rehydrate from disk so a returning user never sees a login screen flash.
  ///
  /// Wrapped, because **this method not finishing means the app never starts**.
  /// The router holds on the splash while the status is `unknown`, so anything
  /// that throws in here — a cached record from an older version that no longer
  /// parses, a malformed JSON blob, a field that changed type — leaves the app
  /// on the logo forever, with no error and no way out but reinstalling.
  ///
  /// Signed-out is the right fallback: the session could not be read, so it has
  /// to be entered again. That is a sign-in screen, not a dead app.
  Future<void> _restore() async {
    try {
      await _restoreFromStorage();
    } catch (error, stack) {
      debugPrint('session restore failed: $error\n$stack');
    } finally {
      // Belt and braces: whatever happened above, the app must leave the
      // splash. `unknown` is the only status the router will not move past.
      if (state.status == AuthStatus.unknown) {
        state = const SessionState(status: AuthStatus.signedOut);
      }
    }
  }

  Future<void> _restoreFromStorage() async {
    final token = await _store.accessToken;
    final cachedUser = _store.user;

    if (token == null || cachedUser == null) {
      state = const SessionState(status: AuthStatus.signedOut);
      return;
    }

    var businesses = <Business>[];
    try {
      businesses = _store.businesses.map(Business.fromJson).toList();
    } catch (_) {
      // A cached shop list this build cannot read is worth discarding, not
      // dying over — the server is asked for a fresh one just below.
      businesses = [];
    }

    // An empty cached list is not proof that this person has no shop — it is
    // equally consistent with the list simply not having been written yet, or
    // with an upgrade that cleared it. `needsBusiness` is derived from this, and
    // it sends the user into registration: someone who already owns a shop
    // would be walked into creating a second one, splitting their data in two.
    //
    // So when there is a valid token but no cached shop, ask the server. If the
    // network is down we fall through with the empty list; registration is then
    // the honest destination, because there is nothing else we can offer.
    if (businesses.isEmpty) {
      try {
        // Bounded, because this runs while the splash is on screen. Dio's own
        // receive timeout is a minute; a minute of logo is indistinguishable
        // from a hang, and the app is perfectly usable without this — it only
        // decides whether the user lands on the dashboard or on registration.
        businesses = await _ref
            .read(businessRepositoryProvider)
            .mine()
            .timeout(const Duration(seconds: 8));
        if (businesses.isNotEmpty) {
          await _store.setBusinesses([for (final b in businesses) b.toJson()]);
        }
      } catch (_) {
        // Offline, slow, or the token is dead — the 401 handler deals with the
        // last of those. None of them may hold the app on its splash screen.
      }
    }

    final activeId = _store.businessId;
    final active = businesses.where((b) => b.id == activeId).firstOrNull ??
        businesses.firstOrNull;

    // Keep the stored active id honest, so the next launch resolves directly.
    if (active != null && active.id != activeId) {
      await _store.setBusinessId(active.id);
    }

    state = SessionState(
      status: AuthStatus.signedIn,
      user: AppUser.fromJson(cachedUser),
      business: active,
      businesses: businesses,
      permissions: _store.permissions,
    );
  }

  void _apply(AuthSession session) {
    state = SessionState(
      status: AuthStatus.signedIn,
      user: session.user,
      business: session.activeBusiness,
      businesses: session.businesses,
      permissions: session.permissions.toSet(),
    );
  }

  Future<void> login(String identifier, String password) async =>
      _apply(await _auth.login(identifier, password));

  Future<void> register({
    required String name,
    required String password,
    String? email,
    String? phone,
    String? businessName,
    String businessType = 'retail',
    String country = 'Pakistan',
  }) async =>
      _apply(await _auth.register(
        name: name,
        password: password,
        email: email,
        phone: phone,
        businessName: businessName,
        businessType: businessType,
        country: country,
      ));

  /// Returns false when the user backed out of the Google sheet — the caller
  /// should treat that as "nothing happened", not as a failure.
  Future<bool> signInWithGoogle({String? businessName}) async {
    final idToken = await GoogleAuth.idToken();
    if (idToken == null) return false;
    _apply(await _auth.googleSignIn(idToken, businessName: businessName));
    return true;
  }

  Future<String?> sendOtp(String identifier) => _auth.sendOtp(identifier);

  Future<void> verifyOtp(String identifier, String code, {String? name}) async =>
      _apply(await _auth.verifyOtp(identifier, code, name: name));

  Future<void> switchBusiness(String businessId) async =>
      _apply(await _auth.switchBusiness(businessId));

  Future<void> signOut() async {
    await _auth.signOut();
    await GoogleAuth.signOut();
    // A shared phone must not hand one shop's cached data — or its unsent
    // work — to whoever signs in next.
    await _ref.read(syncControllerProvider).reset();
    state = const SessionState(status: AuthStatus.signedOut);
  }

  void forceSignOut() {
    _store.signOut();
    unawaited(_ref.read(syncControllerProvider).reset());
    state = const SessionState(status: AuthStatus.signedOut);
  }
}

final sessionProvider = StateNotifierProvider<SessionNotifier, SessionState>(
  SessionNotifier.new,
);

// ── preferences ──────────────────────────────────────────────────
final languageProvider = StateNotifierProvider<LanguageNotifier, String>(
  (ref) => LanguageNotifier(ref.watch(tokenStoreProvider)),
);

class LanguageNotifier extends StateNotifier<String> {
  LanguageNotifier(this._store) : super(_store.language);

  final TokenStore _store;

  Future<void> set(String code) async {
    state = code;
    await _store.setLanguage(code);
  }
}

final themeModeProvider = StateNotifierProvider<ThemeModeNotifier, ThemeMode>(
  (ref) => ThemeModeNotifier(ref.watch(tokenStoreProvider)),
);

/// Whether the first-launch tour has been seen.
///
/// The router needs this to decide between the tour and the sign-in screen, and
/// it needs to be *told* when it changes. `tokenStoreProvider` is overridden
/// with a single instance in `main()`, so watching it hands back the same
/// object forever and never fires again: writing `onboarded` to disk left the
/// router still believing the tour was unfinished, and it redirected straight
/// back to it. That is what made Skip and Get started look like dead buttons.
///
/// Disk stays the source of truth across launches; this mirrors it within one.
final onboardedProvider = StateProvider<bool>(
  (ref) => ref.watch(tokenStoreProvider).onboarded,
);

class ThemeModeNotifier extends StateNotifier<ThemeMode> {
  ThemeModeNotifier(this._store) : super(_parse(_store.themeMode));

  final TokenStore _store;

  static ThemeMode _parse(String value) => switch (value) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };

  Future<void> set(ThemeMode mode) async {
    state = mode;
    await _store.setThemeMode(mode.name);
  }
}

// ── data providers ───────────────────────────────────────────────
final dashboardPeriodProvider = StateProvider<String>((ref) => 'this_month');


// ── instant screens ──────────────────────────────────────────────
/// Emits the last saved copy first, then the server's answer.
///
/// Two frames instead of one, and the first arrives from local storage in a
/// millisecond or two. On a connection to a database several hundred
/// milliseconds away, this is what removes the spinner from every screen.
///
/// If the network then fails **after** cached data was already shown, the error
/// is swallowed on purpose: the user is looking at usable figures, and the sync
/// banner is already telling them the connection is down. Replacing a working
/// screen with a red error page would be strictly worse.
Stream<T> _cachedThenFresh<T>(
  Future<T> Function(void Function(T cached) emit) fetch,
) {
  final controller = StreamController<T>();
  var emittedCached = false;

  fetch((cached) {
    if (controller.isClosed) return;
    emittedCached = true;
    controller.add(cached);
  }).then((fresh) {
    if (!controller.isClosed) controller.add(fresh);
  }).catchError((Object error, StackTrace stack) {
    if (!controller.isClosed && !emittedCached) controller.addError(error, stack);
  }).whenComplete(() {
    if (!controller.isClosed) controller.close();
  });

  return controller.stream;
}

final dashboardProvider = StreamProvider.autoDispose<Dashboard>((ref) {
  final period = ref.watch(dashboardPeriodProvider);
  final repository = ref.watch(reportRepositoryProvider);
  return _cachedThenFresh<Dashboard>(
    (emit) => repository.dashboard(period: period, onCached: emit),
  );
});

final partySearchProvider = StateProvider.autoDispose<String>((ref) => '');
final partyFilterProvider = StateProvider.autoDispose<String>((ref) => 'all');

/// Which tab of the home shell is showing.
///
/// The shell used to take this from the route's `?tab=` parameter alone, read
/// once into a `late` field — so moving between tabs from inside the app did
/// nothing whatsoever. Every route into a list from the dashboard produced a
/// ripple and no change: "2 overdue invoices", "To collect", "To pay", the
/// stock tile, and every assistant link to a list.
///
/// Holding it here makes switching a state change rather than a navigation, so
/// it cannot depend on whether the router decided to rebuild. `?tab=` still
/// seeds it, which is what makes deep links work.
final homeTabProvider = StateProvider<int>((ref) => 0);

/// The party-list chip values the server will accept as a `party_type`.
///
/// The chip row mixes two different things — All, Customer, Supplier, To
/// collect, To pay — and only the middle two are party types. The others
/// describe a balance. Sending "receivable" as a party type made the server
/// reject the whole request, so tapping either balance chip emptied the screen
/// with "Some fields are invalid" rather than filtering it.
const partyTypeFilters = {'customer', 'supplier', 'both'};

/// The `party_type` to send for a chip, or null when the chip means something
/// else. Public so it can be tested; the values must match
/// `party_type`'s pattern in `backend/app/api/v1/endpoints/parties.py`.
String? partyTypeForFilter(String filter) =>
    partyTypeFilters.contains(filter) ? filter : null;

final partiesProvider = StreamProvider.autoDispose<Paged<Party>>((ref) {
  final search = ref.watch(partySearchProvider);
  final filter = ref.watch(partyFilterProvider);
  final repository = ref.watch(partyRepositoryProvider);
  return _cachedThenFresh<Paged<Party>>((emit) => repository.list(
        onCached: emit,
        search: search.isEmpty ? null : search,
        partyType: partyTypeForFilter(filter),
        onlyReceivable: filter == 'receivable',
        onlyPayable: filter == 'payable',
        size: 50,
      ));
});

final partyProvider =
    StreamProvider.autoDispose.family<Party, String>((ref, id) {
  final repository = ref.watch(partyRepositoryProvider);
  return _cachedThenFresh<Party>((emit) => repository.get(id, onCached: emit));
});

final partyLedgerProvider =
    StreamProvider.autoDispose.family<List<LedgerEntry>, String>((ref, id) {
  final repository = ref.watch(partyRepositoryProvider);
  return _cachedThenFresh<List<LedgerEntry>>((emit) async {
    final (entries, _) = await repository.ledger(id, onCached: emit);
    return entries;
  });
});

final itemSearchProvider = StateProvider.autoDispose<String>((ref) => '');
final itemFilterProvider = StateProvider.autoDispose<String>((ref) => 'all');

final itemsProvider = StreamProvider.autoDispose<Paged<Item>>((ref) {
  final search = ref.watch(itemSearchProvider);
  final filter = ref.watch(itemFilterProvider);
  final repository = ref.watch(itemRepositoryProvider);
  return _cachedThenFresh<Paged<Item>>((emit) => repository.list(
        onCached: emit,
        search: search.isEmpty ? null : search,
        onlyLowStock: filter == 'low_stock',
        size: 50,
      ));
});

final itemProvider = StreamProvider.autoDispose.family<Item, String>((ref, id) {
  final repository = ref.watch(itemRepositoryProvider);
  return _cachedThenFresh<Item>((emit) => repository.get(id, onCached: emit));
});

final voucherTypeProvider = StateProvider.autoDispose<String>((ref) => 'sale');
final voucherFilterProvider = StateProvider.autoDispose<String>((ref) => 'all');
final voucherSearchProvider = StateProvider.autoDispose<String>((ref) => '');

final vouchersProvider = StreamProvider.autoDispose<Paged<Voucher>>((ref) {
  final type = ref.watch(voucherTypeProvider);
  final filter = ref.watch(voucherFilterProvider);
  final search = ref.watch(voucherSearchProvider);
  final repository = ref.watch(voucherRepositoryProvider);
  return _cachedThenFresh<Paged<Voucher>>((emit) => repository.list(
        onCached: emit,
        voucherType: type,
        search: search.isEmpty ? null : search,
        onlyUnpaid: filter == 'unpaid',
        onlyOverdue: filter == 'overdue',
        size: 50,
      ));
});

final voucherProvider =
    StreamProvider.autoDispose.family<Voucher, String>((ref, id) {
  final repository = ref.watch(voucherRepositoryProvider);
  return _cachedThenFresh<Voucher>((emit) => repository.get(id, onCached: emit));
});

final stockSummaryProvider =
    StreamProvider.autoDispose<Map<String, dynamic>>((ref) {
  final repository = ref.watch(itemRepositoryProvider);
  return _cachedThenFresh<Map<String, dynamic>>(
    (emit) => repository.stockSummary(onCached: emit),
  );
});

final insightsProvider = FutureProvider.autoDispose<List<Insight>>((ref) async {
  return ref.watch(aiRepositoryProvider).insights();
});

final aiSuggestionsProvider = StreamProvider.autoDispose<List<String>>((ref) {
  final language = ref.watch(languageProvider);
  final repository = ref.watch(aiRepositoryProvider);
  return _cachedThenFresh<List<String>>(
    (emit) => repository.suggestions(language: language, onCached: emit),
  );
});

final expensesProvider = StreamProvider.autoDispose<Paged<Expense>>((ref) {
  final repository = ref.watch(expenseRepositoryProvider);
  return _cachedThenFresh<Paged<Expense>>((emit) => repository.list(onCached: emit));
});

final expenseCategoriesProvider =
    StreamProvider.autoDispose<List<ExpenseCategory>>((ref) {
  final repository = ref.watch(expenseRepositoryProvider);
  return _cachedThenFresh<List<ExpenseCategory>>(
    (emit) => repository.categories(onCached: emit),
  );
});

// ── stock depth: locations, batches, serials ─────────────────────
final godownsProvider = StreamProvider.autoDispose<List<Godown>>((ref) {
  final repository = ref.watch(stockRepositoryProvider);
  return _cachedThenFresh<List<Godown>>((emit) => repository.godowns(onCached: emit));
});

final godownStockProvider =
    FutureProvider.autoDispose.family<List<GodownStockRow>, String>((ref, godownId) {
  return ref.watch(stockRepositoryProvider).stockAt(godownId);
});

/// Where one item's stock sits. Empty until a shop creates its first location.
final itemGodownsProvider =
    FutureProvider.autoDispose.family<List<ItemGodownRow>, String>((ref, itemId) {
  return ref.watch(stockRepositoryProvider).whereItemIs(itemId);
});

final itemBatchesProvider =
    FutureProvider.autoDispose.family<List<ItemBatch>, String>((ref, itemId) {
  return ref.watch(stockRepositoryProvider).batches(itemId);
});

/// How far ahead the expiry watch-list looks.
final expiryWindowProvider = StateProvider.autoDispose<int>((ref) => 30);

final expiringBatchesProvider =
    FutureProvider.autoDispose<List<ExpiringBatch>>((ref) {
  final days = ref.watch(expiryWindowProvider);
  return ref.watch(stockRepositoryProvider).expiring(withinDays: days);
});

/// The sticker sheets and rolls a shop can buy. Fixed data, so it is cached.
final labelSizesProvider = FutureProvider<List<LabelSize>>((ref) {
  return ref.watch(stockRepositoryProvider).labelSizes();
});

// ── repeating bills ──────────────────────────────────────────────
final recurringBillsProvider = FutureProvider.autoDispose<List<RecurringBill>>((ref) {
  return ref.watch(recurringRepositoryProvider).list();
});

/// Raises whatever is due, once per app launch.
///
/// There is no scheduler on the server — it runs on functions that only exist
/// while a request is in flight — so this call is the whole reason a repeating
/// bill repeats. It is deliberately not `autoDispose`: leaving and returning
/// to a screen must not raise the same bills again, and the server's own
/// date check is the second line of defence rather than the first.
final recurringRunProvider = FutureProvider<RecurringRun>((ref) async {
  final session = ref.watch(sessionProvider);
  if (session.status != AuthStatus.signedIn) return const RecurringRun();

  try {
    final run = await ref.read(recurringRepositoryProvider).runDue();
    if (run.created.isNotEmpty) {
      // Real invoices just appeared, so anything counting them is stale.
      ref.invalidate(recurringBillsProvider);
      ref.invalidate(dashboardProvider);
      ref.invalidate(vouchersProvider);
      ref.invalidate(partiesProvider);
      ref.invalidate(itemsProvider);
    }
    return run;
  } catch (_) {
    // A shop with no signal still has to be able to open the app. The bills
    // are still owed and the next launch will raise them.
    return const RecurringRun();
  }
});

// ── rates and offers ─────────────────────────────────────────────
final priceListsProvider = FutureProvider.autoDispose<List<PriceList>>((ref) {
  return ref.watch(pricingRepositoryProvider).lists();
});

final priceEntriesProvider =
    FutureProvider.autoDispose.family<List<PriceEntry>, String>((ref, listId) {
  return ref.watch(pricingRepositoryProvider).entries(listId);
});

final schemesProvider = FutureProvider.autoDispose<List<DiscountScheme>>((ref) {
  return ref.watch(pricingRepositoryProvider).schemes();
});

/// The looks an invoice can print in. Also fixed, also cached.
final invoiceThemesProvider = FutureProvider<List<InvoiceTheme>>((ref) {
  return ref.watch(businessRepositoryProvider).invoiceThemes();
});

final itemSerialsProvider =
    FutureProvider.autoDispose.family<List<ItemSerial>, String>((ref, itemId) {
  return ref.watch(stockRepositoryProvider).serials(itemId);
});

// ── money: accounts, cheques, loans ──────────────────────────────
final bankAccountsProvider = FutureProvider.autoDispose<List<BankAccount>>((ref) {
  return ref.watch(paymentRepositoryProvider).bankAccounts(cache: false);
});

final transfersProvider = FutureProvider.autoDispose<List<AccountTransfer>>((ref) {
  return ref.watch(financeRepositoryProvider).transfers();
});

/// Which cheques the list is showing. Null means every unsettled one.
final chequeFilterProvider = StateProvider.autoDispose<String?>((ref) => null);

final chequesProvider = FutureProvider.autoDispose<List<Cheque>>((ref) {
  final status = ref.watch(chequeFilterProvider);
  return ref.watch(financeRepositoryProvider).cheques(status: status);
});

final chequeSummaryProvider = FutureProvider.autoDispose<ChequeSummary>((ref) {
  return ref.watch(financeRepositoryProvider).chequeSummary();
});

final loansProvider = FutureProvider.autoDispose<List<Loan>>((ref) {
  return ref.watch(financeRepositoryProvider).loans();
});

final loanProvider = FutureProvider.autoDispose.family<Loan, String>((ref, id) {
  return ref.watch(financeRepositoryProvider).loan(id);
});

final loanSummaryProvider = FutureProvider.autoDispose<LoanSummary>((ref) {
  return ref.watch(financeRepositoryProvider).loanSummary();
});

final loanScheduleProvider =
    FutureProvider.autoDispose.family<List<LoanInstalment>, String>((ref, id) {
  return ref.watch(financeRepositoryProvider).loanSchedule(id);
});

final loanPaymentsProvider =
    FutureProvider.autoDispose.family<List<LoanPayment>, String>((ref, id) {
  return ref.watch(financeRepositoryProvider).loanPayments(id);
});

final paymentDirectionProvider = StateProvider.autoDispose<String?>((ref) => null);

final paymentsProvider = StreamProvider.autoDispose<Paged<Payment>>((ref) {
  final direction = ref.watch(paymentDirectionProvider);
  final repository = ref.watch(paymentRepositoryProvider);
  return _cachedThenFresh<Paged<Payment>>(
    (emit) => repository.list(direction: direction, onCached: emit),
  );
});

/// Refreshed on demand — `refresh()` reconciles against live business state, so a
/// paid invoice's reminder disappears rather than lingering.
final notificationsProvider =
    FutureProvider.autoDispose<List<AppNotification>>((ref) async {
  return ref.watch(notificationRepositoryProvider).refresh();
});

final unreadCountProvider = FutureProvider.autoDispose<int>((ref) async {
  return ref.watch(notificationRepositoryProvider).unreadCount();
});

final businessSettingsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  return ref.watch(businessRepositoryProvider).settings();
});

/// Who shares this shop. Kept off the autoDispose fast path deliberately — the
/// list is small and changes rarely, so it survives a trip to the invite sheet.
final teamMembersProvider = FutureProvider.autoDispose<List<TeamMember>>((ref) async {
  return ref.watch(businessRepositoryProvider).members();
});

final businessProfileProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  return ref.watch(businessRepositoryProvider).current();
});

/// True until the shop has a customer, an item and at least one bill — drives the
/// first-run checklist on the dashboard.
final setupProgressProvider = FutureProvider.autoDispose<SetupProgress>((ref) async {
  final parties = await ref.watch(partyRepositoryProvider).list(size: 1);
  final items = await ref.watch(itemRepositoryProvider).list(size: 1);
  final invoices = await ref.watch(voucherRepositoryProvider).list(size: 1);
  return SetupProgress(
    hasParty: parties.total > 0,
    hasItem: items.total > 0,
    hasInvoice: invoices.total > 0,
  );
});

class SetupProgress {
  const SetupProgress({
    required this.hasParty,
    required this.hasItem,
    required this.hasInvoice,
  });

  final bool hasParty;
  final bool hasItem;
  final bool hasInvoice;

  int get done => [hasParty, hasItem, hasInvoice].where((step) => step).length;
  bool get isComplete => done == 3;
}

/// Refreshes every list that a write could have changed.
void invalidateBusinessData(WidgetRef ref) {
  ref.invalidate(dashboardProvider);
  ref.invalidate(partiesProvider);
  ref.invalidate(itemsProvider);
  ref.invalidate(vouchersProvider);
  ref.invalidate(stockSummaryProvider);
}
