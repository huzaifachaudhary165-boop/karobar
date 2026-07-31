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
    void Function(Paged<Item>)? onCached,
  }) async {
    final data = await _api.get('/items',
        onCached: _parsed(onCached, Item.fromJson), query: {
      'page': page,
      'size': size,
      'search': search,
      'category_id': categoryId,
      if (onlyLowStock) 'only_low_stock': true,
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
}

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
