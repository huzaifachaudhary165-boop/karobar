/// Repositories — one thin wrapper per API area.
///
/// Each returns typed models and nothing else; widgets never see raw maps.
library;

import '../core/network/api_client.dart';
import '../core/utils/formatters.dart';
import '../core/storage/token_store.dart';
import 'models.dart';

class AuthRepository {
  AuthRepository(this._api, this._store);

  final ApiClient _api;
  final TokenStore _store;

  Future<AuthSession> register({
    required String name,
    required String password,
    String? email,
    String? phone,
    String? businessName,
    String businessType = 'retail',
    String country = 'Pakistan',
    String language = 'en',
  }) async {
    final data = await _api.post('/auth/register', body: {
      'name': name,
      'password': password,
      if (email != null && email.isNotEmpty) 'email': email,
      if (phone != null && phone.isNotEmpty) 'phone': phone,
      if (businessName != null && businessName.isNotEmpty) 'business_name': businessName,
      'business_type': businessType,
      'country': country,
      'language': language,
    });
    return _persist(AuthSession.fromJson(Map<String, dynamic>.from(data as Map)));
  }

  Future<AuthSession> login(String identifier, String password) async {
    final data = await _api.post('/auth/login', body: {
      'identifier': identifier,
      'password': password,
    });
    return _persist(AuthSession.fromJson(Map<String, dynamic>.from(data as Map)));
  }

  /// Exchanges Google's ID token for a Karobar session.
  ///
  /// The token is verified server-side against Google's public keys, so the app
  /// is only a courier here — it cannot assert who the user is.
  Future<AuthSession> googleSignIn(String idToken, {String? businessName}) async {
    final data = await _api.post('/auth/google', body: {
      'id_token': idToken,
      if (businessName != null && businessName.isNotEmpty) 'business_name': businessName,
    });
    return _persist(AuthSession.fromJson(Map<String, dynamic>.from(data as Map)));
  }

  /// Returns the debug OTP when the server runs in dev mode.
  Future<String?> sendOtp(String identifier, {String purpose = 'login'}) async {
    final data = await _api.post('/auth/otp/send', body: {
      'identifier': identifier,
      'purpose': purpose,
    });
    return (data as Map)['debug_code'] as String?;
  }

  /// Asks the server to email a reset code.
  ///
  /// Throws if no account is registered for [identifier] — that check happens
  /// before anything is sent, so the screen can say so while the user is still
  /// looking at the field they typed it into.
  Future<OtpSent> sendResetCode(String identifier) async {
    final data = await _api.post('/auth/otp/send', body: {
      'identifier': identifier,
      'purpose': 'reset_password',
    });
    return OtpSent.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> resetPassword({
    required String identifier,
    required String code,
    required String newPassword,
  }) async {
    await _api.post('/auth/reset-password', body: {
      'identifier': identifier,
      'code': code,
      'new_password': newPassword,
    });
  }

  Future<AuthSession> verifyOtp(String identifier, String code, {String? name}) async {
    final data = await _api.post('/auth/otp/verify', body: {
      'identifier': identifier,
      'code': code,
      if (name != null) 'name': name,
    });
    return _persist(AuthSession.fromJson(Map<String, dynamic>.from(data as Map)));
  }

  Future<AuthSession> switchBusiness(String businessId) async {
    final data = await _api.post('/auth/switch-business', body: {'business_id': businessId});
    return _persist(AuthSession.fromJson(Map<String, dynamic>.from(data as Map)));
  }

  Future<AppUser> me() async {
    final data = await _api.get('/auth/me');
    return AppUser.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> signOut() async {
    final refresh = await _store.refreshToken;
    try {
      await _api.post('/auth/logout', body: {'refresh_token': refresh ?? ''});
    } catch (_) {
      // Signing out locally must succeed even when the server is unreachable.
    }
    await _store.signOut();
  }

  Future<AuthSession> _persist(AuthSession session) async {
    await _store.saveTokens(access: session.accessToken, refresh: session.refreshToken);
    await _store.setUser(session.user.toJson());
    await _store.setBusinesses(session.businesses.map((b) => b.toJson()).toList());
    await _store.setBusinessId(session.activeBusiness?.id);
    await _store.setPermissions(session.permissions);
    return session;
  }
}

/// Bridges `ApiClient`'s raw-JSON cache callback to a typed one.
///
/// A cached body that no longer parses — because the app was updated and the
/// model changed — is skipped rather than thrown: the network response is
/// moments away and is the one that matters.
void Function(dynamic)? _parsed<T>(
  void Function(Paged<T>)? onCached,
  T Function(Map<String, dynamic>) fromJson,
) {
  if (onCached == null) return null;
  return (raw) {
    try {
      onCached(Paged.fromJson(Map<String, dynamic>.from(raw as Map), fromJson));
    } catch (_) {}
  };
}

/// The same bridge for an endpoint that returns one object rather than a page.
///
/// Detail screens — an invoice, a customer, an item — used to have no cache
/// path at all, so opening one always meant a spinner for the length of a full
/// round trip even though the list it was opened from had just shown the same
/// figures.
void Function(dynamic)? _parsedOne<T>(
  void Function(T)? onCached,
  T Function(Map<String, dynamic>) fromJson,
) {
  if (onCached == null) return null;
  return (raw) {
    try {
      onCached(fromJson(Map<String, dynamic>.from(raw as Map)));
    } catch (_) {}
  };
}

/// And for one that returns a bare JSON list.
void Function(dynamic)? _parsedList<T>(
  void Function(List<T>)? onCached,
  T Function(Map<String, dynamic>) fromJson,
) {
  if (onCached == null) return null;
  return (raw) {
    try {
      onCached((raw as List)
          .map((e) => fromJson(Map<String, dynamic>.from(e as Map)))
          .toList());
    } catch (_) {}
  };
}

class PartyRepository {
  PartyRepository(this._api);

  final ApiClient _api;

  /// [onCached] fires immediately with the last saved page, if there is one, so
  /// the list can paint before the network answers.
  Future<Paged<Party>> list({
    int page = 1,
    int size = 25,
    String? search,
    String? partyType,
    bool onlyReceivable = false,
    bool onlyPayable = false,
    void Function(Paged<Party>)? onCached,
  }) async {
    final data = await _api.get('/parties',
        onCached: _parsed(onCached, Party.fromJson), query: {
      'page': page,
      'size': size,
      'search': search,
      'party_type': partyType,
      if (onlyReceivable) 'only_receivable': true,
      if (onlyPayable) 'only_payable': true,
      'sort': 'name',
      'order': 'asc',
    });
    return Paged.fromJson(Map<String, dynamic>.from(data as Map), Party.fromJson);
  }

  Future<List<Party>> search(String query) async {
    if (query.trim().isEmpty) return const [];
    final data = await _api.get('/parties/search', query: {'q': query, 'limit': 10});
    return (data as List)
        .map((e) => Party.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<Party> get(String id, {void Function(Party)? onCached}) async {
    final data = await _api.get('/parties/$id',
        onCached: _parsedOne(onCached, Party.fromJson));
    return Party.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Party> create(Map<String, dynamic> body) async {
    final data = await _api.post('/parties', body: body);
    return Party.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Party> update(String id, Map<String, dynamic> body) async {
    final data = await _api.patch('/parties/$id', body: body);
    return Party.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> delete(String id) => _api.delete('/parties/$id');

  Future<(List<LedgerEntry>, num)> ledger(
    String id, {
    void Function(List<LedgerEntry>)? onCached,
  }) async {
    final data = Map<String, dynamic>.from(
      await _api.get(
        '/parties/$id/ledger',
        onCached: onCached == null
            ? null
            : (raw) {
                try {
                  onCached(
                    ((raw as Map)['entries'] as List? ?? [])
                        .map((e) =>
                            LedgerEntry.fromJson(Map<String, dynamic>.from(e as Map)))
                        .toList(),
                  );
                } catch (_) {}
              },
      ) as Map,
    );
    final entries = (data['entries'] as List? ?? [])
        .map((e) => LedgerEntry.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
    return (entries, asNum(data['closing_balance']));
  }
}

class ItemRepository {
  ItemRepository(this._api);

  final ApiClient _api;

  Future<Paged<Item>> list({
    int page = 1,
    int size = 25,
    String? search,
    String? categoryId,
    bool onlyLowStock = false,
    // An item a shop has retired should stop appearing — on the list and, more
    // to the point, in the picker on a bill. The app tells shopkeepers to mark
    // an item inactive when it cannot be deleted, and until this was passed
    // that advice changed nothing at all.
    bool? isActive = true,
    void Function(Paged<Item>)? onCached,
  }) async {
    final data = await _api.get('/items',
        onCached: _parsed(onCached, Item.fromJson), query: {
      'page': page,
      'size': size,
      'search': search,
      'category_id': categoryId,
      if (onlyLowStock) 'only_low_stock': true,
      if (isActive != null) 'is_active': isActive,
      'sort': 'name',
      'order': 'asc',
    });
    return Paged.fromJson(Map<String, dynamic>.from(data as Map), Item.fromJson);
  }

  Future<List<Item>> search(String query) async {
    if (query.trim().isEmpty) return const [];
    final data = await _api.get('/items/search', query: {'q': query, 'limit': 10});
    return (data as List)
        .map((e) => Item.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<Item> get(String id, {void Function(Item)? onCached}) async {
    final data =
        await _api.get('/items/$id', onCached: _parsedOne(onCached, Item.fromJson));
    return Item.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Item> byBarcode(String barcode) async {
    final data = await _api.get('/items/barcode/$barcode');
    return Item.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Item> create(Map<String, dynamic> body) async {
    final data = await _api.post('/items', body: body);
    return Item.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Item> update(String id, Map<String, dynamic> body) async {
    final data = await _api.patch('/items/$id', body: body);
    return Item.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> delete(String id) => _api.delete('/items/$id');

  Future<Item> adjustStock(String itemId, num qty, String reason) async {
    final data = await _api.post('/items/stock/adjust', body: {
      'item_id': itemId,
      'qty': qty,
      'reason': reason,
    });
    return Item.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Map<String, dynamic>> stockSummary({
    void Function(Map<String, dynamic>)? onCached,
  }) async =>
      Map<String, dynamic>.from(
        await _api.get(
          '/items/stock/summary',
          onCached: onCached == null
              ? null
              : (raw) {
                  try {
                    onCached(Map<String, dynamic>.from(raw as Map));
                  } catch (_) {}
                },
        ) as Map,
      );
}

class VoucherRepository {
  VoucherRepository(this._api);

  final ApiClient _api;

  Future<Paged<Voucher>> list({
    int page = 1,
    int size = 25,
    String? voucherType,
    String? status,
    String? partyId,
    String? search,
    bool onlyUnpaid = false,
    bool onlyOverdue = false,
    DateTime? startDate,
    DateTime? endDate,
    void Function(Paged<Voucher>)? onCached,
  }) async {
    final data = await _api.get('/vouchers',
        onCached: _parsed(onCached, Voucher.fromJson), query: {
      'page': page,
      'size': size,
      'voucher_type': voucherType,
      'status': status,
      'party_id': partyId,
      'search': search,
      if (onlyUnpaid) 'only_unpaid': true,
      if (onlyOverdue) 'only_overdue': true,
      'start_date': startDate?.toIso8601String().substring(0, 10),
      'end_date': endDate?.toIso8601String().substring(0, 10),
      'sort': 'voucher_date',
      'order': 'desc',
    });
    return Paged.fromJson(Map<String, dynamic>.from(data as Map), Voucher.fromJson);
  }

  Future<Voucher> get(String id, {void Function(Voucher)? onCached}) async {
    final data = await _api.get('/vouchers/$id',
        onCached: _parsedOne(onCached, Voucher.fromJson));
    return Voucher.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Voucher> create(Map<String, dynamic> body) async {
    final data = await _api.post('/vouchers', body: body);
    return Voucher.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// Turns a quotation, order or challan into the document it becomes.
  ///
  /// The server decides what is legal — a purchase order can only become a
  /// purchase bill — so this passes the target straight through rather than
  /// second-guessing it.
  Future<Voucher> convert(String id, String targetType) async {
    final data = await _api.post('/vouchers/$id/convert', body: {
      'target_type': targetType,
    });
    return Voucher.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Voucher> cancel(String id, String? reason) async {
    final data = await _api.post('/vouchers/$id/cancel', body: {'reason': reason});
    return Voucher.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> delete(String id) => _api.delete('/vouchers/$id');

  Future<String> nextNumber(String voucherType) async {
    final data = await _api.get('/vouchers/next-number', query: {'voucher_type': voucherType});
    return (data as Map)['next_number'] as String;
  }

  Future<String> html(String id) async {
    final response = await _api.raw('/vouchers/$id/html');
    return response.data.toString();
  }

  Future<Map<String, dynamic>> share(
    String id, {
    required String channel,
    String? recipient,
    String? message,
  }) async {
    final data = await _api.post('/vouchers/$id/share', body: {
      'channel': channel,
      if (recipient != null) 'recipient': recipient,
      if (message != null) 'message': message,
      'attach_pdf': true,
    });
    return Map<String, dynamic>.from(data as Map);
  }
}

class PaymentRepository {
  PaymentRepository(this._api);

  final ApiClient _api;

  Future<Paged<Payment>> list({
    int page = 1,
    String? direction,
    String? partyId,
    void Function(Paged<Payment>)? onCached,
  }) async {
    final data = await _api.get('/payments',
        onCached: _parsed(onCached, Payment.fromJson), query: {
      'page': page,
      'size': 25,
      'direction': direction,
      'party_id': partyId,
      'sort': 'payment_date',
      'order': 'desc',
    });
    return Paged.fromJson(Map<String, dynamic>.from(data as Map), Payment.fromJson);
  }

  Future<Map<String, dynamic>> settle({
    required String partyId,
    required num amount,
    String direction = 'in',
    String mode = 'cash',
    String? notes,
  }) async {
    final data = await _api.post('/payments/settle', body: {
      'party_id': partyId,
      'amount': amount,
      'direction': direction,
      'mode': mode,
      if (notes != null) 'notes': notes,
    });
    return Map<String, dynamic>.from(data as Map);
  }

  Future<void> delete(String id) => _api.delete('/payments/$id');

  Future<List<Map<String, dynamic>>> accounts() async {
    final data = await _api.get('/payments/accounts');
    return (data as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  Future<List<BankAccount>> bankAccounts({bool cache = true}) async {
    final data = await _api.get('/payments/accounts', cache: cache);
    return (data as List)
        .map((e) => BankAccount.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<BankAccount> createAccount(Map<String, dynamic> body) async {
    final data = await _api.post('/payments/accounts', body: body);
    return BankAccount.fromJson(Map<String, dynamic>.from(data as Map));
  }
}

/// Locations, batches and serial numbers — the depth behind a plain stock figure.
class StockRepository {
  StockRepository(this._api);

  final ApiClient _api;

  // ── locations ──────────────────────────────────────────────────
  Future<List<Godown>> godowns({void Function(List<Godown>)? onCached}) async {
    final data = await _api.get('/items/godowns', onCached: _list(onCached, Godown.fromJson));
    return _parseList(data, Godown.fromJson);
  }

  Future<Godown> createGodown(Map<String, dynamic> body) async {
    final data = await _api.post('/items/godowns', body: body);
    return Godown.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Godown> updateGodown(String id, Map<String, dynamic> body) async {
    final data = await _api.patch('/items/godowns/$id', body: body);
    return Godown.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteGodown(String id) => _api.delete('/items/godowns/$id');

  Future<List<GodownStockRow>> stockAt(String godownId) async {
    final data = await _api.get('/items/godowns/$godownId/stock', cache: false);
    return _parseList(data, GodownStockRow.fromJson);
  }

  Future<List<ItemGodownRow>> whereItemIs(String itemId) async {
    final data = await _api.get('/items/$itemId/godowns', cache: false);
    return _parseList(data, ItemGodownRow.fromJson);
  }

  Future<Map<String, dynamic>> transfer({
    required String itemId,
    required String fromGodownId,
    required String toGodownId,
    required num qty,
    String? batchId,
    String? note,
  }) async {
    final data = await _api.post('/items/stock/transfer', body: {
      'item_id': itemId,
      'from_godown_id': fromGodownId,
      'to_godown_id': toGodownId,
      'qty': qty,
      if (batchId != null) 'batch_id': batchId,
      if (note != null && note.isNotEmpty) 'note': note,
    });
    return Map<String, dynamic>.from(data as Map);
  }

  // ── batches ────────────────────────────────────────────────────
  Future<List<ItemBatch>> batches(String itemId, {bool inStockOnly = false}) async {
    final data = await _api.get(
      '/items/$itemId/batches',
      cache: false,
      query: {'in_stock_only': inStockOnly},
    );
    return _parseList(data, ItemBatch.fromJson);
  }

  Future<ItemBatch> createBatch(Map<String, dynamic> body) async {
    final data = await _api.post('/items/batches', body: body);
    return ItemBatch.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<ItemBatch> updateBatch(String id, Map<String, dynamic> body) async {
    final data = await _api.patch('/items/batches/$id', body: body);
    return ItemBatch.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteBatch(String id) => _api.delete('/items/batches/$id');

  Future<List<ExpiringBatch>> expiring({int withinDays = 30}) async {
    final data = await _api.get(
      '/items/batches/expiring',
      cache: false,
      query: {'within_days': withinDays},
    );
    return _parseList(data, ExpiringBatch.fromJson);
  }

  // ── serials ────────────────────────────────────────────────────
  Future<List<ItemSerial>> serials(String itemId, {String? status}) async {
    final data = await _api.get(
      '/items/$itemId/serials',
      cache: false,
      query: {'serial_status': status},
    );
    return _parseList(data, ItemSerial.fromJson);
  }

  Future<SerialAddResult> addSerials({
    required String itemId,
    required List<String> serials,
    num? purchasePrice,
    int? warrantyMonths,
    String? godownId,
  }) async {
    final data = await _api.post('/items/serials', body: {
      'item_id': itemId,
      'serials': serials,
      if (purchasePrice != null) 'purchase_price': purchasePrice,
      if (warrantyMonths != null) 'warranty_months': warrantyMonths,
      if (godownId != null) 'godown_id': godownId,
    });
    return SerialAddResult.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Map<String, dynamic>> lookupSerial(String serialNumber) async {
    final data = await _api.get('/items/serials/lookup/$serialNumber', cache: false);
    return Map<String, dynamic>.from(data as Map);
  }

  // ── barcode labels ─────────────────────────────────────────────
  Future<List<LabelSize>> labelSizes() async {
    final data = await _api.get('/items/labels/sizes');
    return _parseList(data, LabelSize.fromJson);
  }

  /// The printable sheet, as HTML.
  ///
  /// Returned as text rather than a file so the app can hand it straight to the
  /// system print dialog or a browser — every Android phone can print HTML, and
  /// not every shop has a label printer paired.
  Future<String> labelSheet({
    required List<({String itemId, int qty})> items,
    required String size,
    bool showName = true,
    bool showPrice = true,
    bool showMrp = false,
    bool showCode = true,
    bool showShop = false,
    int startAt = 1,
  }) async {
    final response = await _api.post('/items/labels', body: {
      'items': [
        for (final row in items) {'item_id': row.itemId, 'qty': row.qty},
      ],
      'size': size,
      'show_name': showName,
      'show_price': showPrice,
      'show_mrp': showMrp,
      'show_code': showCode,
      'show_shop': showShop,
      'start_at': startAt,
    });
    // The endpoint answers text/html, so Dio hands back the document itself
    // rather than a decoded map.
    return response.toString();
  }

  /// Mints an in-store barcode for an item that arrived without one.
  Future<String> assignBarcode(String itemId) async {
    final data = await _api.post(
      '/items/labels/assign-barcode',
      query: {'item_id': itemId},
    );
    return (data as Map)['barcode'].toString();
  }
}

/// Transfers between own accounts, cheques and loans.
class FinanceRepository {
  FinanceRepository(this._api);

  final ApiClient _api;

  // ── transfers ──────────────────────────────────────────────────
  Future<List<AccountTransfer>> transfers({String? accountId}) async {
    final data = await _api.get(
      '/finance/transfers',
      cache: false,
      query: {'account_id': accountId},
    );
    return _parseList(data, AccountTransfer.fromJson);
  }

  Future<AccountTransfer> transfer({
    required String fromAccountId,
    required String toAccountId,
    required num amount,
    num charges = 0,
    String? referenceNumber,
    String? notes,
  }) async {
    final data = await _api.post('/finance/transfers', body: {
      'from_account_id': fromAccountId,
      'to_account_id': toAccountId,
      'amount': amount,
      if (charges > 0) 'charges': charges,
      if (referenceNumber != null && referenceNumber.isNotEmpty)
        'reference_number': referenceNumber,
      if (notes != null && notes.isNotEmpty) 'notes': notes,
    });
    return AccountTransfer.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteTransfer(String id) => _api.delete('/finance/transfers/$id');

  // ── cheques ────────────────────────────────────────────────────
  Future<List<Cheque>> cheques({String? status, String? direction}) async {
    final data = await _api.get('/finance/cheques', cache: false, query: {
      'cheque_status': status,
      'direction': direction,
    });
    return _parseList(data, Cheque.fromJson);
  }

  Future<ChequeSummary> chequeSummary() async {
    final data = await _api.get('/finance/cheques/summary', cache: false);
    return ChequeSummary.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Cheque> setChequeStatus(String paymentId, String status, {String? note}) async {
    final data = await _api.patch('/finance/cheques/$paymentId', body: {
      'status': status,
      if (note != null && note.isNotEmpty) 'note': note,
    });
    return Cheque.fromJson(Map<String, dynamic>.from(data as Map));
  }

  // ── loans ──────────────────────────────────────────────────────
  Future<List<Loan>> loans({String? status}) async {
    final data = await _api.get('/finance/loans', cache: false, query: {'loan_status': status});
    return _parseList(data, Loan.fromJson);
  }

  Future<Loan> loan(String id) async {
    final data = await _api.get('/finance/loans/$id', cache: false);
    return Loan.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<LoanSummary> loanSummary() async {
    final data = await _api.get('/finance/loans/summary', cache: false);
    return LoanSummary.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Loan> createLoan(Map<String, dynamic> body) async {
    final data = await _api.post('/finance/loans', body: body);
    return Loan.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteLoan(String id) => _api.delete('/finance/loans/$id');

  Future<List<LoanInstalment>> loanSchedule(String id) async {
    final data = await _api.get('/finance/loans/$id/schedule', cache: false);
    return _parseList(data, LoanInstalment.fromJson);
  }

  Future<List<LoanPayment>> loanPayments(String id) async {
    final data = await _api.get('/finance/loans/$id/payments', cache: false);
    return _parseList(data, LoanPayment.fromJson);
  }

  Future<LoanPayment> repayLoan(
    String id, {
    required num amount,
    String? accountId,
    String? referenceNumber,
    String? notes,
  }) async {
    final data = await _api.post('/finance/loans/$id/payments', body: {
      'amount': amount,
      if (accountId != null) 'account_id': accountId,
      if (referenceNumber != null && referenceNumber.isNotEmpty)
        'reference_number': referenceNumber,
      if (notes != null && notes.isNotEmpty) 'notes': notes,
    });
    return LoanPayment.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteLoanPayment(String loanId, String paymentId) =>
      _api.delete('/finance/loans/$loanId/payments/$paymentId');
}

/// Price lists, discount offers, and what a line should cost.
class PricingRepository {
  PricingRepository(this._api);

  final ApiClient _api;

  Future<List<PriceList>> lists() async {
    final data = await _api.get('/pricing/lists', cache: false);
    return _parseList(data, PriceList.fromJson);
  }

  Future<PriceList> createList(Map<String, dynamic> body) async {
    final data = await _api.post('/pricing/lists', body: body);
    return PriceList.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteList(String id) => _api.delete('/pricing/lists/$id');

  Future<List<PriceEntry>> entries(String listId) async {
    final data = await _api.get('/pricing/lists/$listId/items', cache: false);
    return _parseList(data, PriceEntry.fromJson);
  }

  Future<void> setEntry(String listId, String itemId, num price, {num? minQty}) =>
      _api.put('/pricing/lists/$listId/items', body: {
        'item_id': itemId,
        'price': price,
        if (minQty != null) 'min_qty': minQty,
      });

  Future<void> removeEntry(String listId, String itemId) =>
      _api.delete('/pricing/lists/$listId/items/$itemId');

  Future<List<DiscountScheme>> schemes({bool onlyRunning = false}) async {
    final data = await _api.get(
      '/pricing/schemes',
      cache: false,
      query: {'only_running': onlyRunning},
    );
    return _parseList(data, DiscountScheme.fromJson);
  }

  Future<DiscountScheme> createScheme(Map<String, dynamic> body) async {
    final data = await _api.post('/pricing/schemes', body: body);
    return DiscountScheme.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteScheme(String id) => _api.delete('/pricing/schemes/$id');

  /// What these lines should cost for this customer, right now.
  ///
  /// Asked as lines are added rather than on save: the bill charges what the
  /// shopkeeper read out to the customer, so the server is never allowed to
  /// reprice a voucher it is handed.
  Future<List<QuoteLine>> quote({
    required List<({String itemId, num qty})> lines,
    String? partyId,
  }) async {
    final data = await _api.post('/pricing/quote', body: {
      'lines': [
        for (final line in lines) {'item_id': line.itemId, 'qty': line.qty},
      ],
      if (partyId != null) 'party_id': partyId,
    });
    return _parseList(data, QuoteLine.fromJson);
  }
}

/// Bills that repeat.
class RecurringRepository {
  RecurringRepository(this._api);

  final ApiClient _api;

  Future<List<RecurringBill>> list() async {
    final data = await _api.get('/recurring', cache: false);
    return _parseList(data, RecurringBill.fromJson);
  }

  Future<RecurringBill> create(Map<String, dynamic> body) async {
    final data = await _api.post('/recurring', body: body);
    return RecurringBill.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<RecurringBill> update(String id, Map<String, dynamic> body) async {
    final data = await _api.patch('/recurring/$id', body: body);
    return RecurringBill.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> delete(String id) => _api.delete('/recurring/$id');

  Future<void> runOne(String id) => _api.post('/recurring/$id/run');

  /// Raises everything that has come due.
  ///
  /// There is no scheduler on the server — it runs on functions that only
  /// exist while a request is in flight — so the app asking on open is what
  /// makes a repeating bill repeat at all.
  Future<RecurringRun> runDue() async {
    final data = await _api.post('/recurring/run');
    return RecurringRun.fromJson(Map<String, dynamic>.from(data as Map));
  }
}

/// Every report the app can produce, and their data.
class ReportCatalogueRepository {
  ReportCatalogueRepository(this._api);

  final ApiClient _api;

  Future<List<ReportGroup>> catalogue() async {
    final data = await _api.get('/reports/catalogue');
    return _parseList((data as Map)['groups'], ReportGroup.fromJson);
  }

  /// Fetches whatever a catalogue entry points at.
  ///
  /// Deliberately untyped: the viewer renders whatever shape comes back, so a
  /// report added on the server needs no matching model here.
  Future<Map<String, dynamic>> fetch(String endpoint) async {
    final data = await _api.get(endpoint, cache: false);
    return Map<String, dynamic>.from(data as Map);
  }
}

/// Pakistani sales tax.
class TaxRepository {
  TaxRepository(this._api);

  final ApiClient _api;

  Future<TaxReturn> monthlyReturn({int? month, int? year}) async {
    final data = await _api.get('/fbr/return', cache: false, query: {
      'month': month,
      'year': year,
    });
    return TaxReturn.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Map<String, dynamic>> suggestedRates() async {
    final data = await _api.get('/fbr/rates');
    return Map<String, dynamic>.from(data as Map);
  }

  /// The sales register, as the portal's own CSV.
  Future<String> annexureC({int? month, int? year}) async {
    final response = await _api.raw('/fbr/annexure-c', query: {
      'month': month,
      'year': year,
    });
    return response.data.toString();
  }
}

/// Loyalty points.
class LoyaltyRepository {
  LoyaltyRepository(this._api);

  final ApiClient _api;

  Future<LoyaltyProgram?> program() async {
    final data = await _api.get('/loyalty/program', cache: false);
    if (data == null) return null;
    return LoyaltyProgram.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<LoyaltyProgram> saveProgram(Map<String, dynamic> body) async {
    final data = await _api.put('/loyalty/program', body: body);
    return LoyaltyProgram.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<int> balance(String partyId) async {
    final data = await _api.get('/loyalty/balance/$partyId', cache: false);
    return asNum((data as Map)['balance']).toInt();
  }

  Future<List<LoyaltyEntry>> history(String partyId) async {
    final data = await _api.get('/loyalty/history/$partyId', cache: false);
    return _parseList(data, LoyaltyEntry.fromJson);
  }

  Future<LoyaltyQuote> quote(String partyId, num billTotal) async {
    final data = await _api.post('/loyalty/quote', body: {
      'party_id': partyId,
      'bill_total': billTotal,
    });
    return LoyaltyQuote.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> redeem({
    required String partyId,
    required int points,
    required num billTotal,
    String? voucherId,
  }) =>
      _api.post('/loyalty/redeem', body: {
        'party_id': partyId,
        'points': points,
        'bill_total': billTotal,
        if (voucherId != null) 'voucher_id': voucherId,
      });

  Future<void> adjust(String partyId, int points, String note) =>
      _api.post('/loyalty/adjust', body: {
        'party_id': partyId,
        'points': points,
        'note': note,
      });

  Future<List<LoyaltyHolder>> topHolders() async {
    final data = await _api.get('/loyalty/top', cache: false);
    return _parseList(data, LoyaltyHolder.fromJson);
  }
}

/// Recipes and production runs.
class ManufacturingRepository {
  ManufacturingRepository(this._api);

  final ApiClient _api;

  Future<List<Recipe>> recipes() async {
    final data = await _api.get('/manufacturing/recipes', cache: false);
    return _parseList(data, Recipe.fromJson);
  }

  Future<Recipe> createRecipe(Map<String, dynamic> body) async {
    final data = await _api.post('/manufacturing/recipes', body: body);
    return Recipe.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> deleteRecipe(String id) => _api.delete('/manufacturing/recipes/$id');

  /// What making this many would need, asked before committing to it.
  Future<RecipeCosting> costing(String recipeId, num qty) async {
    final data = await _api.get(
      '/manufacturing/recipes/$recipeId/costing',
      cache: false,
      query: {'qty': qty},
    );
    return RecipeCosting.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<List<ProductionRun>> runs() async {
    final data = await _api.get('/manufacturing/runs', cache: false);
    return _parseList(data, ProductionRun.fromJson);
  }

  Future<ProductionRun> make(String recipeId, num qty, {String? notes}) async {
    final data = await _api.post('/manufacturing/runs', body: {
      'bom_id': recipeId,
      'qty': qty,
      if (notes != null && notes.isNotEmpty) 'notes': notes,
    });
    return ProductionRun.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> undoRun(String id) => _api.delete('/manufacturing/runs/$id');
}

/// Turns a raw list response into models, tolerating a null body.
List<T> _parseList<T>(dynamic data, T Function(Map<String, dynamic>) parse) =>
    (data as List? ?? const [])
        .map((e) => parse(Map<String, dynamic>.from(e as Map)))
        .toList();

/// Adapts an `onCached` callback that wants models to the raw callback the
/// client hands back.
void Function(dynamic)? _list<T>(
  void Function(List<T>)? onCached,
  T Function(Map<String, dynamic>) parse,
) =>
    onCached == null ? null : (raw) => onCached(_parseList(raw, parse));

class ExpenseRepository {
  ExpenseRepository(this._api);

  final ApiClient _api;

  Future<Paged<Expense>> list({
    int page = 1,
    int size = 50,
    String? categoryId,
    String? search,
    DateTime? startDate,
    DateTime? endDate,
    void Function(Paged<Expense>)? onCached,
  }) async {
    final data = await _api.get('/expenses',
        onCached: _parsed(onCached, Expense.fromJson), query: {
      'page': page,
      'size': size,
      'category_id': categoryId,
      'search': search,
      'start_date': startDate?.toIso8601String().substring(0, 10),
      'end_date': endDate?.toIso8601String().substring(0, 10),
      'sort': 'expense_date',
      'order': 'desc',
    });
    return Paged.fromJson(Map<String, dynamic>.from(data as Map), Expense.fromJson);
  }

  Future<Expense> create(Map<String, dynamic> body) async {
    final data = await _api.post('/expenses', body: body);
    return Expense.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> delete(String id) => _api.delete('/expenses/$id');

  Future<List<ExpenseCategory>> categories({
    void Function(List<ExpenseCategory>)? onCached,
  }) async {
    final data = await _api.get('/expenses/categories',
        onCached: _parsedList(onCached, ExpenseCategory.fromJson));
    return (data as List)
        .map((e) => ExpenseCategory.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<List<Map<String, dynamic>>> breakdown({
    required DateTime startDate,
    required DateTime endDate,
  }) async {
    final data = await _api.get('/expenses/breakdown', query: {
      'start_date': startDate.toIso8601String().substring(0, 10),
      'end_date': endDate.toIso8601String().substring(0, 10),
    });
    return (data as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }
}

class BusinessRepository {
  BusinessRepository(this._api);

  final ApiClient _api;

  Future<Map<String, dynamic>> current() async =>
      Map<String, dynamic>.from(await _api.get('/businesses/current') as Map);

  /// Every shop this user belongs to, straight from the server.
  ///
  /// Used to settle the question "does this person actually have a shop?" when
  /// the cached list on disk is empty. Guessing wrong sends someone who already
  /// owns a shop into registration to create a second one.
  Future<List<Business>> mine() async {
    final data = await _api.get('/businesses', cache: false);
    return (data as List)
        .map((e) => Business.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<Map<String, dynamic>> update(Map<String, dynamic> body) async =>
      Map<String, dynamic>.from(await _api.patch('/businesses/current', body: body) as Map);

  Future<Map<String, dynamic>> settings() async =>
      Map<String, dynamic>.from(await _api.get('/businesses/current/settings') as Map);

  /// The looks an invoice can print in. Fixed data, so it is cached.
  Future<List<InvoiceTheme>> invoiceThemes() async {
    final data = await _api.get('/businesses/invoice-themes');
    return _parseList(data, InvoiceTheme.fromJson);
  }

  /// A sample bill rendered in one look, for the picker.
  Future<String> invoicePreview(String themeKey) async {
    final data = await _api.get(
      '/businesses/current/invoice-preview',
      cache: false,
      query: {'theme': themeKey},
    );
    return data.toString();
  }

  Future<Map<String, dynamic>> updateSettings(Map<String, dynamic> body) async =>
      Map<String, dynamic>.from(
        await _api.patch('/businesses/current/settings', body: body) as Map,
      );

  Future<List<TeamMember>> members() async {
    final data = await _api.get('/businesses/current/members');
    return (data as List)
        .map((e) => TeamMember.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  /// Invites someone by email or phone. If they have no Karobar account yet the
  /// server creates a placeholder; they claim it by signing in with that same
  /// email or number, so there is no invite link to lose.
  Future<TeamMember> inviteMember({
    String? email,
    String? phone,
    String? name,
    required String role,
  }) async {
    final data = await _api.post('/businesses/current/members', body: {
      if (email != null && email.isNotEmpty) 'email': email,
      if (phone != null && phone.isNotEmpty) 'phone': phone,
      if (name != null && name.isNotEmpty) 'name': name,
      'role': role,
    });
    return TeamMember.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> updateMember(String memberId, {String? role, bool? isActive}) =>
      _api.patch('/businesses/current/members/$memberId', body: {
        if (role != null) 'role': role,
        if (isActive != null) 'is_active': isActive,
      });

  Future<void> removeMember(String memberId) =>
      _api.delete('/businesses/current/members/$memberId');

  Future<Map<String, dynamic>> integrations() async =>
      Map<String, dynamic>.from(await _api.get('/integrations') as Map);
}

class NotificationRepository {
  NotificationRepository(this._api);

  final ApiClient _api;

  Future<List<AppNotification>> list({bool onlyUnread = false}) async {
    final data = await _api.get('/notifications', query: {
      'size': 50,
      if (onlyUnread) 'only_unread': true,
    });
    return (Map<String, dynamic>.from(data as Map)['items'] as List)
        .map((e) => AppNotification.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<int> unreadCount() async {
    final data = await _api.get('/notifications/count');
    return asNum((data as Map)['unread']).toInt();
  }

  /// Recomputes the list from current business state — paid invoices and
  /// restocked items drop off on their own.
  Future<List<AppNotification>> refresh() async {
    final data = await _api.post('/notifications/refresh');
    return (data as List)
        .map((e) => AppNotification.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<void> markRead(String id) => _api.post('/notifications/$id/read');
  Future<void> markAllRead() => _api.post('/notifications/read-all');
  Future<void> clear() => _api.delete('/notifications');
}

class ReportRepository {
  ReportRepository(this._api);

  final ApiClient _api;

  Future<Dashboard> dashboard({
    String period = 'this_month',
    void Function(Dashboard)? onCached,
  }) async {
    final data = await _api.get(
      '/reports/dashboard',
      query: {'period': period},
      onCached: onCached == null
          ? null
          : (raw) => onCached(Dashboard.fromJson(Map<String, dynamic>.from(raw as Map))),
    );
    return Dashboard.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<Map<String, dynamic>> profitLoss({String period = 'this_month'}) async =>
      Map<String, dynamic>.from(
        await _api.get('/reports/profit-loss', query: {'period': period}) as Map,
      );

  Future<Map<String, dynamic>> ageing({String direction = 'receivable'}) async =>
      Map<String, dynamic>.from(
        await _api.get('/reports/ageing', query: {'direction': direction}) as Map,
      );

  Future<Map<String, dynamic>> salesReport({
    String period = 'this_month',
    String groupBy = 'day',
  }) async =>
      Map<String, dynamic>.from(
        await _api.get('/reports/sales', query: {'period': period, 'group_by': groupBy}) as Map,
      );

  Future<Map<String, dynamic>> daybook({String period = 'today'}) async =>
      Map<String, dynamic>.from(
        await _api.get('/reports/daybook', query: {'period': period}) as Map,
      );
}

class AiRepository {
  AiRepository(this._api);

  final ApiClient _api;

  Future<ChatReply> chat({
    required String message,
    String? conversationId,
    String? language,
    List<String> attachmentIds = const [],
    bool allowWrites = true,
  }) async {
    final data = await _api.post(
      '/ai/chat',
      body: {
        'message': message,
        if (conversationId != null) 'conversation_id': conversationId,
        if (language != null) 'language': language,
        if (attachmentIds.isNotEmpty) 'attachment_ids': attachmentIds,
        'allow_writes': allowWrites,
      },
      timeout: const Duration(seconds: 120),
    );
    return ChatReply.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<ChatReply> voice({
    required String transcript,
    String? conversationId,
    double? confidence,
  }) async {
    final data = await _api.post(
      '/ai/voice',
      body: {
        'transcript': transcript,
        if (conversationId != null) 'conversation_id': conversationId,
        if (confidence != null) 'confidence': confidence,
      },
      timeout: const Duration(seconds: 120),
    );
    return ChatReply.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// The prompt chips on the assistant screen.
  ///
  /// Cached because they barely change and the screen is unusable without them:
  /// waiting eight seconds on a round trip before offering anything to tap is
  /// most of the reason the assistant feels slow to open.
  Future<List<String>> suggestions({
    String language = 'en',
    void Function(List<String>)? onCached,
  }) async {
    final data = await _api.get(
      '/ai/suggestions',
      query: {'language': language},
      onCached: onCached == null
          ? null
          : (raw) {
              try {
                onCached(((raw as Map)['suggestions'] as List)
                    .map((e) => e.toString())
                    .toList());
              } catch (_) {}
            },
    );
    return ((data as Map)['suggestions'] as List).map((e) => e.toString()).toList();
  }

  Future<List<ChatMessage>> history(String conversationId) async {
    final data = Map<String, dynamic>.from(
      await _api.get('/ai/conversations/$conversationId') as Map,
    );
    return (data['messages'] as List? ?? [])
        .map((e) => ChatMessage.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<List<Map<String, dynamic>>> conversations() async {
    final data = await _api.get('/ai/conversations');
    return (data as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  Future<String> uploadImage(List<int> bytes, String filename) async {
    final data = await _api.upload(
      '/files',
      bytes: bytes,
      filename: filename,
      fields: {'folder': 'scans'},
    );
    return (data as Map)['id'] as String;
  }

  /// Sends text the device already read off a bill.
  ///
  /// Character recognition happens on the phone, so this call carries text, not
  /// an image — which is why it is quick even on a weak connection.
  /// [attachmentId] is optional and only links a photo the user chose to keep.
  Future<OcrJob> scan(
    String rawText, {
    String? attachmentId,
    String documentType = 'auto',
  }) async {
    final data = await _api.post(
      '/ai/ocr/scan',
      body: {
        'raw_text': rawText,
        if (attachmentId != null) 'attachment_id': attachmentId,
        'document_type': documentType,
      },
      timeout: const Duration(seconds: 120),
    );
    return OcrJob.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<OcrJob> applyScan(String jobId, {String target = 'purchase'}) async {
    final data = await _api.post('/ai/ocr/apply', body: {
      'job_id': jobId,
      'target': target,
      'create_missing_items': true,
      'create_missing_party': true,
    });
    return OcrJob.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<List<Insight>> insights({String period = 'this_month', bool refresh = false}) async {
    final data = await _api.post(
      '/ai/insights',
      body: {'period': period, 'refresh': refresh},
      timeout: const Duration(seconds: 90),
    );
    return (data as List)
        .map((e) => Insight.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }
}

class SyncRepository {
  SyncRepository(this._api);

  final ApiClient _api;

  Future<Map<String, dynamic>> bootstrap() async =>
      Map<String, dynamic>.from(await _api.get('/sync/bootstrap') as Map);

  Future<Map<String, dynamic>> pull({int since = 0}) async =>
      Map<String, dynamic>.from(await _api.get('/sync/pull', query: {'since': since}) as Map);

  Future<Map<String, dynamic>> push({
    required String deviceId,
    required List<Map<String, dynamic>> changes,
  }) async =>
      Map<String, dynamic>.from(
        await _api.post('/sync/push', body: {
          'device_id': deviceId,
          'platform': 'mobile',
          'changes': changes,
        }) as Map,
      );

  Future<Map<String, dynamic>> status() async =>
      Map<String, dynamic>.from(await _api.get('/sync/status') as Map);
}

/// Getting the shop's data out — backup, restore and the GST return.
class DataRepository {
  DataRepository(this._api);

  final ApiClient _api;

  /// The whole business as a JSON file. Returned as bytes so the caller can
  /// hand it straight to the share sheet without a temporary server round trip.
  Future<({List<int> bytes, String filename})> backup() async {
    final response = await _api.raw('/data/backup');
    final disposition = response.headers.value('content-disposition') ?? '';
    final match = RegExp('filename="([^"]+)"').firstMatch(disposition);
    return (
      bytes: (response.data as String).codeUnits,
      filename: match?.group(1) ?? 'karobar-backup.json',
    );
  }

  Future<Map<String, dynamic>> restore(List<int> bytes, String filename) async {
    final data = await _api.upload(
      '/data/restore',
      bytes: bytes,
      filename: filename,
    );
    return Map<String, dynamic>.from(data as Map);
  }

  Future<Map<String, dynamic>> gstr1({
    required DateTime start,
    required DateTime end,
  }) async {
    final data = await _api.get('/data/gstr1', query: {
      'start_date': Fmt.iso(start),
      'end_date': Fmt.iso(end),
    });
    return Map<String, dynamic>.from(data as Map);
  }

  Future<String> gstr1Csv({required DateTime start, required DateTime end}) async {
    final response = await _api.raw('/data/gstr1', query: {
      'start_date': Fmt.iso(start),
      'end_date': Fmt.iso(end),
      'format': 'csv',
    });
    return response.data as String;
  }

  /// Deletes bills, payments and expenses. Customers and items stay.
  Future<String> clearTransactions() async {
    final data = await _api.delete('/data/clear');
    return (data as Map)['message']?.toString() ?? 'Cleared.';
  }
}
