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
  Future<void> _restore() async {
    final token = await _store.accessToken;
    final cachedUser = _store.user;

    if (token == null || cachedUser == null) {
      state = const SessionState(status: AuthStatus.signedOut);
      return;
    }

    var businesses = _store.businesses.map(Business.fromJson).toList();

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
        businesses = await _ref.read(businessRepositoryProvider).mine();
        if (businesses.isNotEmpty) {
          await _store.setBusinesses([for (final b in businesses) b.toJson()]);
        }
      } catch (_) {
        // Offline, or the token is dead — the 401 handler deals with the latter.
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

final partiesProvider = StreamProvider.autoDispose<Paged<Party>>((ref) {
  final search = ref.watch(partySearchProvider);
  final filter = ref.watch(partyFilterProvider);
  final repository = ref.watch(partyRepositoryProvider);
  return _cachedThenFresh<Paged<Party>>((emit) => repository.list(
        onCached: emit,
        search: search.isEmpty ? null : search,
        partyType: filter == 'all' ? null : filter,
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

final aiSuggestionsProvider = FutureProvider.autoDispose<List<String>>((ref) async {
  final language = ref.watch(languageProvider);
  return ref.watch(aiRepositoryProvider).suggestions(language: language);
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
