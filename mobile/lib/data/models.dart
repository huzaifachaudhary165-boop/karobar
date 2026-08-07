/// API data transfer objects.
///
/// Hand-written rather than generated: the shapes are stable, the parsing rules
/// are lenient on purpose (a missing optional field must never crash a list
/// screen), and every numeric field goes through the same coercion helper.
library;

// ── parsing helpers ──────────────────────────────────────────────
/// Money and quantities arrive as JSON **strings**, not numbers.
///
/// The server stores them as `Decimal` and Pydantic serialises a Decimal as a
/// string so no precision is lost in transit. Reading one with `as num?` throws
/// `type 'String' is not a subtype of type 'num?'` — which is exactly what took
/// the Items tab down. Anything reading a raw response map must come through
/// here, not cast.
num asNum(dynamic value) => switch (value) {
      null => 0,
      final num n => n,
      final String s => num.tryParse(s) ?? 0,
      _ => 0,
    };

num? asNumOrNull(dynamic value) => value == null ? null : asNum(value);

num _num(dynamic value) => asNum(value);

num? _numOrNull(dynamic value) => asNumOrNull(value);

String _str(dynamic value, [String fallback = '']) => value?.toString() ?? fallback;

bool _bool(dynamic value) => value == true || value == 1 || value == 'true';

DateTime? _date(dynamic value) =>
    value == null ? null : DateTime.tryParse(value.toString())?.toLocal();

List<Map<String, dynamic>> _maps(dynamic value) => value is List
    ? value.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList()
    : const [];

// ── auth ─────────────────────────────────────────────────────────
class AppUser {
  const AppUser({
    required this.id,
    required this.name,
    this.email,
    this.phone,
    this.avatarUrl,
    this.language = 'en',
    this.activeBusinessId,
  });

  final String id;
  final String name;
  final String? email;
  final String? phone;
  final String? avatarUrl;
  final String language;
  final String? activeBusinessId;

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: _str(json['id']),
        name: _str(json['name'], 'User'),
        email: json['email'] as String?,
        phone: json['phone'] as String?,
        avatarUrl: json['avatar_url'] as String?,
        language: _str(json['language'], 'en'),
        activeBusinessId: json['active_business_id'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'email': email,
        'phone': phone,
        'avatar_url': avatarUrl,
        'language': language,
        'active_business_id': activeBusinessId,
      };
}

class Business {
  const Business({
    required this.id,
    required this.name,
    this.businessType = 'retail',
    this.currencySymbol = 'Rs',
    this.currency = 'PKR',
    this.logoUrl,
    this.role,
    this.plan = 'free',
  });

  final String id;
  final String name;
  final String businessType;
  final String currencySymbol;
  final String currency;
  final String? logoUrl;
  final String? role;
  final String plan;

  String get symbol => '$currencySymbol ';

  factory Business.fromJson(Map<String, dynamic> json) => Business(
        id: _str(json['id']),
        name: _str(json['name'], 'My Business'),
        businessType: _str(json['business_type'], 'retail'),
        currencySymbol: _str(json['currency_symbol'], 'Rs'),
        currency: _str(json['currency'], 'PKR'),
        logoUrl: json['logo_url'] as String?,
        role: json['role'] as String?,
        plan: _str(json['plan'], 'free'),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'business_type': businessType,
        'currency_symbol': currencySymbol,
        'currency': currency,
        'logo_url': logoUrl,
        'role': role,
        'plan': plan,
      };
}

class AuthSession {
  const AuthSession({
    required this.user,
    required this.accessToken,
    required this.refreshToken,
    required this.businesses,
    this.activeBusiness,
    this.permissions = const [],
    this.isNewUser = false,
  });

  final AppUser user;
  final String accessToken;
  final String refreshToken;
  final List<Business> businesses;
  final Business? activeBusiness;
  final List<String> permissions;
  final bool isNewUser;

  factory AuthSession.fromJson(Map<String, dynamic> json) {
    final tokens = Map<String, dynamic>.from(json['tokens'] as Map);
    final active = json['active_business'];
    return AuthSession(
      user: AppUser.fromJson(Map<String, dynamic>.from(json['user'] as Map)),
      accessToken: _str(tokens['access_token']),
      refreshToken: _str(tokens['refresh_token']),
      businesses: _maps(json['businesses']).map(Business.fromJson).toList(),
      activeBusiness:
          active is Map ? Business.fromJson(Map<String, dynamic>.from(active)) : null,
      permissions:
          (json['permissions'] as List?)?.map((e) => e.toString()).toList() ?? const [],
      isNewUser: _bool(json['is_new_user']),
    );
  }
}

/// The server's answer to "send a one-time code".
///
/// [delivered] is the part that matters: the code is valid whether or not the
/// email went out, so the screen uses this to avoid telling someone to go and
/// check an inbox when the send actually failed.
class OtpSent {
  const OtpSent({
    required this.message,
    required this.delivered,
    this.expiresIn = 300,
    this.debugCode,
  });

  final String message;
  final bool delivered;
  final int expiresIn;

  /// Only ever set while the server runs in dev mode.
  final String? debugCode;

  factory OtpSent.fromJson(Map<String, dynamic> json) => OtpSent(
        message: _str(json['message']),
        // Absent on an older server; assume it went out rather than alarm
        // someone whose code is on its way.
        delivered: json['delivered'] == null || _bool(json['delivered']),
        expiresIn: json['expires_in'] == null ? 300 : asNum(json['expires_in']).toInt(),
        debugCode: json['debug_code'] as String?,
      );
}

// ── parties ──────────────────────────────────────────────────────
class Party {
  const Party({
    required this.id,
    required this.name,
    this.partyType = 'customer',
    this.phone,
    this.email,
    this.balance = 0,
    this.creditLimit,
    this.isOverCreditLimit = false,
    this.totalSales = 0,
    this.transactionCount = 0,
    this.lastTransactionAt,
    this.billingAddress,
    this.city,
    this.gstin,
    this.revision = 1,
  });

  final String id;
  final String name;
  final String partyType;
  final String? phone;
  final String? email;
  final num balance;
  final num? creditLimit;
  final bool isOverCreditLimit;
  final num totalSales;
  final int transactionCount;
  final DateTime? lastTransactionAt;
  final String? billingAddress;
  final String? city;
  final String? gstin;
  final int revision;

  bool get isCustomer => partyType == 'customer' || partyType == 'both';
  bool get owesUs => balance > 0;
  num get outstanding => balance.abs();

  factory Party.fromJson(Map<String, dynamic> json) => Party(
        id: _str(json['id']),
        name: _str(json['name']),
        partyType: _str(json['party_type'], 'customer'),
        phone: json['phone'] as String?,
        email: json['email'] as String?,
        balance: _num(json['balance']),
        creditLimit: _numOrNull(json['credit_limit']),
        isOverCreditLimit: _bool(json['is_over_credit_limit']),
        totalSales: _num(json['total_sales']),
        transactionCount: _num(json['transaction_count']).toInt(),
        lastTransactionAt: _date(json['last_transaction_at']),
        billingAddress: json['billing_address'] as String?,
        city: json['city'] as String?,
        gstin: json['gstin'] as String?,
        revision: _num(json['revision']).toInt(),
      );
}

class LedgerEntry {
  const LedgerEntry({
    required this.date,
    required this.entryType,
    required this.description,
    this.referenceNumber,
    this.referenceId,
    this.debit = 0,
    this.credit = 0,
    this.balance = 0,
  });

  final DateTime date;
  final String entryType;
  final String description;
  final String? referenceNumber;
  final String? referenceId;
  final num debit;
  final num credit;
  final num balance;

  factory LedgerEntry.fromJson(Map<String, dynamic> json) => LedgerEntry(
        date: _date(json['date']) ?? DateTime.now(),
        entryType: _str(json['entry_type']),
        description: _str(json['description']),
        referenceNumber: json['reference_number'] as String?,
        referenceId: json['reference_id'] as String?,
        debit: _num(json['debit']),
        credit: _num(json['credit']),
        balance: _num(json['balance']),
      );
}

// ── items ────────────────────────────────────────────────────────
class Item {
  const Item({
    required this.id,
    required this.name,
    this.sku,
    this.barcode,
    this.unitLabel = 'Pcs',
    this.salePrice = 0,
    this.purchasePrice = 0,
    this.stockQty = 0,
    this.lowStockQty,
    this.taxRate = 0,
    this.isLowStock = false,
    this.trackInventory = true,
    this.stockValue = 0,
    this.imageUrl,
    this.categoryName,
    this.itemType = 'product',
    this.revision = 1,
  });

  final String id;
  final String name;
  final String? sku;
  final String? barcode;
  final String unitLabel;
  final num salePrice;
  final num purchasePrice;
  final num stockQty;
  final num? lowStockQty;
  final num taxRate;
  final bool isLowStock;
  final bool trackInventory;
  final num stockValue;
  final String? imageUrl;
  final String? categoryName;
  final String itemType;
  final int revision;

  bool get isOutOfStock => trackInventory && stockQty <= 0;

  String get stockLabel {
    if (!trackInventory) return 'Service';
    return '${stockQty.toStringAsFixed(stockQty == stockQty.roundToDouble() ? 0 : 2)} $unitLabel';
  }

  factory Item.fromJson(Map<String, dynamic> json) => Item(
        id: _str(json['id']),
        name: _str(json['name']),
        sku: json['sku'] as String?,
        barcode: json['barcode'] as String?,
        unitLabel: _str(json['unit_label'], 'Pcs'),
        salePrice: _num(json['sale_price']),
        purchasePrice: _num(json['purchase_price']),
        stockQty: _num(json['stock_qty']),
        lowStockQty: _numOrNull(json['low_stock_qty']),
        taxRate: _num(json['tax_rate']),
        isLowStock: _bool(json['is_low_stock']),
        trackInventory: json['track_inventory'] == null ? true : _bool(json['track_inventory']),
        stockValue: _num(json['stock_value']),
        imageUrl: json['image_url'] as String?,
        categoryName: json['category_name'] as String?,
        itemType: _str(json['item_type'], 'product'),
        revision: _num(json['revision']).toInt(),
      );
}

// ── invoices ─────────────────────────────────────────────────────
class VoucherLine {
  const VoucherLine({
    required this.itemName,
    this.itemId,
    this.qty = 1,
    this.rate = 0,
    this.unitLabel = 'Pcs',
    this.discountAmount = 0,
    this.taxRate = 0,
    this.taxAmount = 0,
    this.total = 0,
  });

  final String itemName;
  final String? itemId;
  final num qty;
  final num rate;
  final String unitLabel;
  final num discountAmount;
  final num taxRate;
  final num taxAmount;
  final num total;

  factory VoucherLine.fromJson(Map<String, dynamic> json) => VoucherLine(
        itemName: _str(json['item_name']),
        itemId: json['item_id'] as String?,
        qty: _num(json['qty']),
        rate: _num(json['rate']),
        unitLabel: _str(json['unit_label'], 'Pcs'),
        discountAmount: _num(json['discount_amount']),
        taxRate: _num(json['tax_rate']),
        taxAmount: _num(json['tax_amount']),
        total: _num(json['total']),
      );

  Map<String, dynamic> toRequest() => {
        if (itemId != null) 'item_id': itemId,
        'item_name': itemName,
        'qty': qty,
        'rate': rate,
        if (taxRate > 0) 'tax_rate': taxRate,
      };
}

class Voucher {
  const Voucher({
    required this.id,
    required this.number,
    required this.voucherType,
    required this.status,
    required this.voucherDate,
    this.dueDate,
    this.partyId,
    this.partyName,
    this.partyPhone,
    this.subtotal = 0,
    this.discountAmount = 0,
    this.taxAmount = 0,
    this.total = 0,
    this.paidAmount = 0,
    this.balanceAmount = 0,
    this.profit = 0,
    this.isOverdue = false,
    this.daysOverdue = 0,
    this.itemCount = 0,
    this.lines = const [],
    this.notes,
    this.source = 'manual',
    this.convertibleTo = const [],
  });

  final String id;
  final String number;
  final String voucherType;
  final String status;
  final DateTime voucherDate;
  final DateTime? dueDate;
  final String? partyId;
  final String? partyName;
  final String? partyPhone;
  final num subtotal;
  final num discountAmount;
  final num taxAmount;
  final num total;
  final num paidAmount;
  final num balanceAmount;
  final num profit;
  final bool isOverdue;
  final int daysOverdue;
  final int itemCount;
  final List<VoucherLine> lines;
  final String? notes;
  final String source;

  /// Document types this one may still become, decided by the server.
  ///
  /// The app offers exactly these and nothing else, so a conversion the server
  /// would refuse — a purchase order into a sale invoice, say — is never on
  /// screen to be tapped.
  final List<String> convertibleTo;

  bool get isPaid => balanceAmount <= 0.005;
  bool get isSale => voucherType == 'sale';
  bool get fromAi => source == 'ai' || source == 'ocr';
  bool get isConverted => status == 'converted';
  bool get canConvert => convertibleTo.isNotEmpty;

  String get typeLabel => switch (voucherType) {
        'sale' => 'Sale invoice',
        'purchase' => 'Purchase bill',
        'sale_return' => 'Credit note',
        'purchase_return' => 'Debit note',
        'quotation' => 'Quotation',
        'proforma' => 'Proforma invoice',
        'sale_order' => 'Sale order',
        'purchase_order' => 'Purchase order',
        'delivery_challan' => 'Delivery challan',
        _ => voucherType.replaceAll('_', ' '),
      };

  factory Voucher.fromJson(Map<String, dynamic> json) => Voucher(
        id: _str(json['id']),
        number: _str(json['number']),
        voucherType: _str(json['voucher_type'], 'sale'),
        status: _str(json['status'], 'unpaid'),
        voucherDate: _date(json['voucher_date']) ?? DateTime.now(),
        dueDate: _date(json['due_date']),
        partyId: json['party_id'] as String?,
        partyName: json['party_name'] as String?,
        partyPhone: json['party_phone'] as String?,
        subtotal: _num(json['subtotal']),
        discountAmount: _num(json['discount_amount']),
        taxAmount: _num(json['tax_amount']),
        total: _num(json['total']),
        paidAmount: _num(json['paid_amount']),
        balanceAmount: _num(json['balance_amount']),
        profit: _num(json['profit']),
        isOverdue: _bool(json['is_overdue']),
        daysOverdue: _num(json['days_overdue']).toInt(),
        itemCount: _num(json['item_count']).toInt(),
        lines: _maps(json['lines']).map(VoucherLine.fromJson).toList(),
        notes: json['notes'] as String?,
        source: _str(json['source'], 'manual'),
        convertibleTo: (json['convertible_to'] as List? ?? const [])
            .map((e) => e.toString())
            .toList(),
      );
}

class Payment {
  const Payment({
    required this.id,
    required this.number,
    required this.direction,
    required this.paymentDate,
    this.partyId,
    this.partyName,
    this.amount = 0,
    this.unallocatedAmount = 0,
    this.mode = 'cash',
  });

  final String id;
  final String number;
  final String direction;
  final DateTime paymentDate;
  final String? partyId;
  final String? partyName;
  final num amount;
  final num unallocatedAmount;
  final String mode;

  bool get isIncoming => direction == 'in';

  factory Payment.fromJson(Map<String, dynamic> json) => Payment(
        id: _str(json['id']),
        number: _str(json['number']),
        direction: _str(json['direction'], 'in'),
        paymentDate: _date(json['payment_date']) ?? DateTime.now(),
        partyId: json['party_id'] as String?,
        partyName: json['party_name'] as String?,
        amount: _num(json['amount']),
        unallocatedAmount: _num(json['unallocated_amount']),
        mode: _str(json['mode'], 'cash'),
      );
}

class Expense {
  const Expense({
    required this.id,
    required this.number,
    required this.title,
    required this.expenseDate,
    this.categoryName,
    this.amount = 0,
    this.taxAmount = 0,
    this.total = 0,
    this.paymentMode = 'cash',
    this.vendorName,
    this.isPaid = true,
    this.source = 'manual',
  });

  final String id;
  final String number;
  final String title;
  final DateTime expenseDate;
  final String? categoryName;
  final num amount;
  final num taxAmount;
  final num total;
  final String paymentMode;
  final String? vendorName;
  final bool isPaid;
  final String source;

  factory Expense.fromJson(Map<String, dynamic> json) => Expense(
        id: _str(json['id']),
        number: _str(json['number']),
        title: _str(json['title']),
        expenseDate: _date(json['expense_date']) ?? DateTime.now(),
        categoryName: json['category_name'] as String?,
        amount: _num(json['amount']),
        taxAmount: _num(json['tax_amount']),
        total: _num(json['total']),
        paymentMode: _str(json['payment_mode'], 'cash'),
        vendorName: json['vendor_name'] as String?,
        isPaid: json['is_paid'] == null ? true : _bool(json['is_paid']),
        source: _str(json['source'], 'manual'),
      );
}

class ExpenseCategory {
  const ExpenseCategory({
    required this.id,
    required this.name,
    this.icon,
    this.spentThisMonth = 0,
    this.expenseCount = 0,
    this.monthlyBudget,
  });

  final String id;
  final String name;
  final String? icon;
  final num spentThisMonth;
  final int expenseCount;
  final num? monthlyBudget;

  factory ExpenseCategory.fromJson(Map<String, dynamic> json) => ExpenseCategory(
        id: _str(json['id']),
        name: _str(json['name']),
        icon: json['icon'] as String?,
        spentThisMonth: _num(json['spent_this_month']),
        expenseCount: _num(json['expense_count']).toInt(),
        monthlyBudget: _numOrNull(json['monthly_budget']),
      );
}

class AppNotification {
  const AppNotification({
    required this.id,
    required this.kind,
    required this.title,
    this.body,
    this.data,
    this.entityType,
    this.entityId,
    this.isRead = false,
    this.createdAt,
  });

  final String id;
  final String kind;
  final String title;
  final String? body;
  final Map<String, dynamic>? data;
  final String? entityType;
  final String? entityId;
  final bool isRead;
  final DateTime? createdAt;

  /// Where tapping the notification should take the user.
  String? get route => data?['route']?.toString();

  factory AppNotification.fromJson(Map<String, dynamic> json) => AppNotification(
        id: _str(json['id']),
        kind: _str(json['kind']),
        title: _str(json['title']),
        body: json['body'] as String?,
        data: json['data'] as Map<String, dynamic>?,
        entityType: json['entity_type'] as String?,
        entityId: json['entity_id'] as String?,
        isRead: _bool(json['is_read']),
        createdAt: _date(json['created_at']),
      );
}

// ── reports ──────────────────────────────────────────────────────
class Trend {
  const Trend({this.value = 0, this.previous, this.changePercent, this.direction = 'flat'});

  final num value;
  final num? previous;
  final num? changePercent;
  final String direction;

  factory Trend.fromJson(Map<String, dynamic>? json) => json == null
      ? const Trend()
      : Trend(
          value: _num(json['value']),
          previous: _numOrNull(json['previous']),
          changePercent: _numOrNull(json['change_percent']),
          direction: _str(json['direction'], 'flat'),
        );
}

class SeriesPoint {
  const SeriesPoint({required this.label, this.value = 0, this.secondary});

  final String label;
  final num value;
  final num? secondary;

  factory SeriesPoint.fromJson(Map<String, dynamic> json) => SeriesPoint(
        label: _str(json['label']),
        value: _num(json['value']),
        secondary: _numOrNull(json['secondary']),
      );
}

class Dashboard {
  const Dashboard({
    required this.periodLabel,
    required this.startDate,
    required this.endDate,
    this.currencySymbol = 'Rs',
    this.sales = const Trend(),
    this.purchases = const Trend(),
    this.expenses = const Trend(),
    this.profit = const Trend(),
    this.collections = const Trend(),
    this.receivable = 0,
    this.payable = 0,
    this.cashInHand = 0,
    this.bankBalance = 0,
    this.stockValue = 0,
    this.invoiceCount = 0,
    this.unpaidInvoiceCount = 0,
    this.overdueInvoiceCount = 0,
    this.overdueAmount = 0,
    this.lowStockCount = 0,
    this.salesSeries = const [],
    this.topItems = const [],
    this.topParties = const [],
    this.recentActivity = const [],
    this.alerts = const [],
  });

  final String periodLabel;
  final DateTime startDate;
  final DateTime endDate;
  final String currencySymbol;
  final Trend sales;
  final Trend purchases;
  final Trend expenses;
  final Trend profit;
  final Trend collections;
  final num receivable;
  final num payable;
  final num cashInHand;
  final num bankBalance;
  final num stockValue;
  final int invoiceCount;
  final int unpaidInvoiceCount;
  final int overdueInvoiceCount;
  final num overdueAmount;
  final int lowStockCount;
  final List<SeriesPoint> salesSeries;
  final List<Map<String, dynamic>> topItems;
  final List<Map<String, dynamic>> topParties;
  final List<Map<String, dynamic>> recentActivity;
  final List<Map<String, dynamic>> alerts;

  factory Dashboard.fromJson(Map<String, dynamic> json) => Dashboard(
        periodLabel: _str(json['period_label'], 'this_month'),
        startDate: _date(json['start_date']) ?? DateTime.now(),
        endDate: _date(json['end_date']) ?? DateTime.now(),
        currencySymbol: _str(json['currency_symbol'], 'Rs'),
        sales: Trend.fromJson(json['sales'] as Map<String, dynamic>?),
        purchases: Trend.fromJson(json['purchases'] as Map<String, dynamic>?),
        expenses: Trend.fromJson(json['expenses'] as Map<String, dynamic>?),
        profit: Trend.fromJson(json['profit'] as Map<String, dynamic>?),
        collections: Trend.fromJson(json['collections'] as Map<String, dynamic>?),
        receivable: _num(json['receivable']),
        payable: _num(json['payable']),
        cashInHand: _num(json['cash_in_hand']),
        bankBalance: _num(json['bank_balance']),
        stockValue: _num(json['stock_value']),
        invoiceCount: _num(json['invoice_count']).toInt(),
        unpaidInvoiceCount: _num(json['unpaid_invoice_count']).toInt(),
        overdueInvoiceCount: _num(json['overdue_invoice_count']).toInt(),
        overdueAmount: _num(json['overdue_amount']),
        lowStockCount: _num(json['low_stock_count']).toInt(),
        salesSeries: _maps(json['sales_series']).map(SeriesPoint.fromJson).toList(),
        topItems: _maps(json['top_items']),
        topParties: _maps(json['top_parties']),
        recentActivity: _maps(json['recent_activity']),
        alerts: _maps(json['alerts']),
      );
}

// ── AI ───────────────────────────────────────────────────────────
class AiAction {
  const AiAction({
    required this.tool,
    required this.label,
    this.status = 'done',
    this.summary,
    this.entityType,
    this.entityId,
    this.deepLink,
    this.error,
  });

  final String tool;
  final String label;
  final String status;
  final String? summary;
  final String? entityType;
  final String? entityId;
  final String? deepLink;
  final String? error;

  bool get succeeded => status == 'done';

  factory AiAction.fromJson(Map<String, dynamic> json) => AiAction(
        tool: _str(json['tool']),
        label: _str(json['label']),
        status: _str(json['status'], 'done'),
        summary: json['summary'] as String?,
        entityType: json['entity_type'] as String?,
        entityId: json['entity_id'] as String?,
        deepLink: json['deep_link'] as String?,
        error: json['error'] as String?,
      );
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    this.actions = const [],
    this.createdAt,
    this.isPending = false,
    this.error,
  });

  final String id;
  final String role;
  final String content;
  final List<AiAction> actions;
  final DateTime? createdAt;
  final bool isPending;
  final String? error;

  bool get isUser => role == 'user';

  ChatMessage copyWith({String? content, bool? isPending, String? error}) => ChatMessage(
        id: id,
        role: role,
        content: content ?? this.content,
        actions: actions,
        createdAt: createdAt,
        isPending: isPending ?? this.isPending,
        error: error ?? this.error,
      );

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        id: _str(json['id']),
        role: _str(json['role'], 'assistant'),
        content: _str(json['content']),
        actions: _maps(json['actions']).map(AiAction.fromJson).toList(),
        createdAt: _date(json['created_at']),
      );
}

class ChatReply {
  const ChatReply({
    required this.conversationId,
    required this.messageId,
    required this.reply,
    this.actions = const [],
    this.suggestions = const [],
    this.language = 'en',
  });

  final String conversationId;
  final String messageId;
  final String reply;
  final List<AiAction> actions;
  final List<String> suggestions;
  final String language;

  factory ChatReply.fromJson(Map<String, dynamic> json) => ChatReply(
        conversationId: _str(json['conversation_id']),
        messageId: _str(json['message_id']),
        reply: _str(json['reply']),
        actions: _maps(json['actions']).map(AiAction.fromJson).toList(),
        suggestions:
            (json['suggestions'] as List?)?.map((e) => e.toString()).toList() ?? const [],
        language: _str(json['language'], 'en'),
      );
}

class OcrJob {
  const OcrJob({
    required this.id,
    required this.status,
    this.documentType = 'purchase_bill',
    this.extracted = const {},
    this.confidence,
    this.warnings = const [],
    this.createdVoucherId,
    this.createdExpenseId,
    this.error,
  });

  final String id;
  final String status;
  final String documentType;
  final Map<String, dynamic> extracted;
  final num? confidence;
  final List<String> warnings;
  final String? createdVoucherId;
  final String? createdExpenseId;
  final String? error;

  bool get isComplete => status == 'completed' || status == 'applied';
  bool get isApplied => status == 'applied';
  bool get isLowConfidence => (confidence ?? 0) < 0.6;

  factory OcrJob.fromJson(Map<String, dynamic> json) => OcrJob(
        id: _str(json['id']),
        status: _str(json['status'], 'pending'),
        documentType: _str(json['document_type'], 'purchase_bill'),
        extracted: Map<String, dynamic>.from(json['extracted'] as Map? ?? {}),
        confidence: _numOrNull(json['confidence']),
        warnings: (json['warnings'] as List?)?.map((e) => e.toString()).toList() ?? const [],
        createdVoucherId: json['created_voucher_id'] as String?,
        createdExpenseId: json['created_expense_id'] as String?,
        error: json['error'] as String?,
      );
}

class Insight {
  const Insight({
    required this.id,
    required this.kind,
    required this.severity,
    required this.title,
    required this.body,
    this.action,
  });

  final String id;
  final String kind;
  final String severity;
  final String title;
  final String body;
  final Map<String, dynamic>? action;

  factory Insight.fromJson(Map<String, dynamic> json) => Insight(
        id: _str(json['id']),
        kind: _str(json['kind'], 'trend'),
        severity: _str(json['severity'], 'info'),
        title: _str(json['title']),
        body: _str(json['body']),
        action: json['action'] as Map<String, dynamic>?,
      );
}

// ── stock depth ──────────────────────────────────────────────────
/// A place stock physically sits: the shop, a godown, a second branch.
class Godown {
  const Godown({
    required this.id,
    required this.name,
    this.address,
    this.isDefault = false,
    this.itemCount = 0,
    this.stockValue = 0,
  });

  final String id;
  final String name;
  final String? address;
  final bool isDefault;
  final int itemCount;
  final num stockValue;

  factory Godown.fromJson(Map<String, dynamic> json) => Godown(
        id: _str(json['id']),
        name: _str(json['name']),
        address: json['address'] as String?,
        isDefault: _bool(json['is_default']),
        itemCount: _num(json['item_count']).toInt(),
        stockValue: _num(json['stock_value']),
      );
}

/// One item's holding at one location.
class GodownStockRow {
  const GodownStockRow({
    required this.itemId,
    required this.itemName,
    this.sku,
    this.unitLabel = 'Pcs',
    this.qty = 0,
    this.value = 0,
  });

  final String itemId;
  final String itemName;
  final String? sku;
  final String unitLabel;
  final num qty;
  final num value;

  factory GodownStockRow.fromJson(Map<String, dynamic> json) => GodownStockRow(
        itemId: _str(json['item_id']),
        itemName: _str(json['item_name']),
        sku: json['sku'] as String?,
        unitLabel: _str(json['unit_label'], 'Pcs'),
        qty: _num(json['qty']),
        value: _num(json['value']),
      );
}

/// Where one item's stock is spread across locations.
class ItemGodownRow {
  const ItemGodownRow({
    required this.godownId,
    required this.godownName,
    this.isDefault = false,
    this.qty = 0,
  });

  final String godownId;
  final String godownName;
  final bool isDefault;
  final num qty;

  factory ItemGodownRow.fromJson(Map<String, dynamic> json) => ItemGodownRow(
        godownId: _str(json['godown_id']),
        godownName: _str(json['godown_name']),
        isDefault: _bool(json['is_default']),
        qty: _num(json['qty']),
      );
}

/// A lot of stock with its own dates — the unit a pharmacy actually thinks in.
class ItemBatch {
  const ItemBatch({
    required this.id,
    required this.itemId,
    required this.batchNumber,
    this.manufactureDate,
    this.expiryDate,
    this.qty = 0,
    this.purchasePrice,
    this.salePrice,
    this.mrp,
    this.isExpired = false,
    this.daysToExpiry,
  });

  final String id;
  final String itemId;
  final String batchNumber;
  final DateTime? manufactureDate;
  final DateTime? expiryDate;
  final num qty;
  final num? purchasePrice;
  final num? salePrice;
  final num? mrp;
  final bool isExpired;
  final int? daysToExpiry;

  /// Close enough to expiry that a shop should be moving it now.
  bool get isExpiringSoon =>
      !isExpired && daysToExpiry != null && daysToExpiry! <= 30;

  factory ItemBatch.fromJson(Map<String, dynamic> json) => ItemBatch(
        id: _str(json['id']),
        itemId: _str(json['item_id']),
        batchNumber: _str(json['batch_number']),
        manufactureDate: _date(json['manufacture_date']),
        expiryDate: _date(json['expiry_date']),
        qty: _num(json['qty']),
        purchasePrice: _numOrNull(json['purchase_price']),
        salePrice: _numOrNull(json['sale_price']),
        mrp: _numOrNull(json['mrp']),
        isExpired: _bool(json['is_expired']),
        daysToExpiry: (json['days_to_expiry'] as num?)?.toInt(),
      );
}

/// A batch shown on the expiry watch-list, with the item it belongs to.
class ExpiringBatch {
  const ExpiringBatch({
    required this.batch,
    required this.itemId,
    required this.itemName,
    this.unitLabel = 'Pcs',
    this.value = 0,
  });

  final ItemBatch batch;
  final String itemId;
  final String itemName;
  final String unitLabel;
  final num value;

  int? get daysToExpiry => batch.daysToExpiry;
  bool get isExpired => batch.isExpired;

  factory ExpiringBatch.fromJson(Map<String, dynamic> json) => ExpiringBatch(
        batch: ItemBatch.fromJson(
          Map<String, dynamic>.from(json['batch'] as Map? ?? const {}),
        ),
        itemId: _str(json['item_id']),
        itemName: _str(json['item_name']),
        unitLabel: _str(json['unit_label'], 'Pcs'),
        value: _num(json['value']),
      );
}

/// One physical unit: an IMEI, a chassis number, a warranty serial.
class ItemSerial {
  const ItemSerial({
    required this.id,
    required this.itemId,
    required this.serialNumber,
    this.status = 'in_stock',
    this.purchasePrice,
    this.salePrice,
    this.warrantyMonths,
    this.warrantyUntil,
    this.inWarranty = false,
    this.soldAt,
    this.note,
  });

  final String id;
  final String itemId;
  final String serialNumber;
  final String status;
  final num? purchasePrice;
  final num? salePrice;
  final int? warrantyMonths;
  final DateTime? warrantyUntil;
  final bool inWarranty;
  final DateTime? soldAt;
  final String? note;

  bool get isAvailable => status == 'in_stock' || status == 'returned';

  factory ItemSerial.fromJson(Map<String, dynamic> json) => ItemSerial(
        id: _str(json['id']),
        itemId: _str(json['item_id']),
        serialNumber: _str(json['serial_number']),
        status: _str(json['status'], 'in_stock'),
        purchasePrice: _numOrNull(json['purchase_price']),
        salePrice: _numOrNull(json['sale_price']),
        warrantyMonths: (json['warranty_months'] as num?)?.toInt(),
        warrantyUntil: _date(json['warranty_until']),
        inWarranty: _bool(json['in_warranty']),
        soldAt: _date(json['sold_at']),
        note: json['note'] as String?,
      );
}

/// What came back from registering a batch of serials.
class SerialAddResult {
  const SerialAddResult({
    this.added = const [],
    this.duplicates = const [],
    this.addedCount = 0,
    this.availableCount = 0,
  });

  final List<ItemSerial> added;
  final List<String> duplicates;
  final int addedCount;
  final int availableCount;

  factory SerialAddResult.fromJson(Map<String, dynamic> json) => SerialAddResult(
        added: _maps(json['added']).map(ItemSerial.fromJson).toList(),
        duplicates: (json['duplicates'] as List? ?? const [])
            .map((e) => e.toString())
            .toList(),
        addedCount: _num(json['added_count']).toInt(),
        availableCount: _num(json['available_count']).toInt(),
      );
}

/// One of the looks an invoice can print in.
class InvoiceTheme {
  const InvoiceTheme({
    required this.key,
    required this.name,
    this.layout = 'band',
    this.accent = '#F97316',
    this.paper = 'A4',
    this.density = 'regular',
    this.isRoll = false,
  });

  final String key;
  final String name;
  final String layout;
  final String accent;
  final String paper;
  final String density;
  final bool isRoll;

  /// The accent as a Flutter colour, falling back to the brand orange.
  ///
  /// A malformed hex from an older build must not take the picker down — it is
  /// a swatch, not a number anything depends on.
  int get accentValue {
    final hex = accent.replaceAll('#', '');
    if (hex.length != 6) return 0xFFF97316;
    return int.tryParse('FF$hex', radix: 16) ?? 0xFFF97316;
  }

  factory InvoiceTheme.fromJson(Map<String, dynamic> json) => InvoiceTheme(
        key: _str(json['key']),
        name: _str(json['name']),
        layout: _str(json['layout'], 'band'),
        accent: _str(json['accent'], '#F97316'),
        paper: _str(json['paper'], 'A4'),
        density: _str(json['density'], 'regular'),
        isRoll: _bool(json['is_roll']),
      );
}

/// A sticker sheet or roll, named the way a shop buys it.
class LabelSize {
  const LabelSize({
    required this.key,
    required this.name,
    this.labelWidthMm = 38,
    this.labelHeightMm = 21,
    this.columns = 5,
    this.rows = 13,
    this.perSheet = 65,
    this.isRoll = false,
  });

  final String key;
  final String name;
  final double labelWidthMm;
  final double labelHeightMm;
  final int columns;
  final int rows;
  final int perSheet;
  final bool isRoll;

  factory LabelSize.fromJson(Map<String, dynamic> json) => LabelSize(
        key: _str(json['key']),
        name: _str(json['name']),
        labelWidthMm: _num(json['label_width_mm']).toDouble(),
        labelHeightMm: _num(json['label_height_mm']).toDouble(),
        columns: _num(json['columns']).toInt(),
        rows: _num(json['rows']).toInt(),
        perSheet: _num(json['per_sheet']).toInt(),
        isRoll: _bool(json['is_roll']),
      );
}

// ── money ────────────────────────────────────────────────────────
/// A cash drawer, bank account or mobile wallet.
class BankAccount {
  const BankAccount({
    required this.id,
    required this.name,
    this.accountType = 'cash',
    this.bankName,
    this.accountNumber,
    this.balance = 0,
    this.isDefault = false,
  });

  final String id;
  final String name;
  final String accountType;
  final String? bankName;
  final String? accountNumber;
  final num balance;
  final bool isDefault;

  bool get isCash => accountType == 'cash';

  factory BankAccount.fromJson(Map<String, dynamic> json) => BankAccount(
        id: _str(json['id']),
        name: _str(json['name']),
        accountType: _str(json['account_type'], 'cash'),
        bankName: json['bank_name'] as String?,
        accountNumber: json['account_number'] as String?,
        balance: _num(json['balance']),
        isDefault: _bool(json['is_default']),
      );
}

/// Money moved between the shop's own accounts.
class AccountTransfer {
  const AccountTransfer({
    required this.id,
    required this.fromAccountId,
    required this.toAccountId,
    required this.transferDate,
    this.fromAccountName,
    this.toAccountName,
    this.amount = 0,
    this.charges = 0,
    this.totalDebited = 0,
    this.referenceNumber,
    this.notes,
  });

  final String id;
  final String fromAccountId;
  final String toAccountId;
  final DateTime transferDate;
  final String? fromAccountName;
  final String? toAccountName;
  final num amount;
  final num charges;
  final num totalDebited;
  final String? referenceNumber;
  final String? notes;

  factory AccountTransfer.fromJson(Map<String, dynamic> json) => AccountTransfer(
        id: _str(json['id']),
        fromAccountId: _str(json['from_account_id']),
        toAccountId: _str(json['to_account_id']),
        transferDate: _date(json['transfer_date']) ?? DateTime.now(),
        fromAccountName: json['from_account_name'] as String?,
        toAccountName: json['to_account_name'] as String?,
        amount: _num(json['amount']),
        charges: _num(json['charges']),
        totalDebited: _num(json['total_debited']),
        referenceNumber: json['reference_number'] as String?,
        notes: json['notes'] as String?,
      );
}

/// A cheque written or received, and where it has got to.
class Cheque {
  const Cheque({
    required this.id,
    required this.number,
    required this.direction,
    required this.paymentDate,
    this.partyId,
    this.partyName,
    this.amount = 0,
    this.chequeDate,
    this.status = 'pending',
    this.referenceNumber,
    this.isOverdue = false,
    this.daysUntilDue,
  });

  final String id;
  final String number;
  final String direction;
  final DateTime paymentDate;
  final String? partyId;
  final String? partyName;
  final num amount;
  final DateTime? chequeDate;
  final String status;
  final String? referenceNumber;
  final bool isOverdue;
  final int? daysUntilDue;

  bool get isIncoming => direction == 'in';
  bool get isSettled => status == 'cleared' || status == 'bounced' || status == 'cancelled';

  factory Cheque.fromJson(Map<String, dynamic> json) => Cheque(
        id: _str(json['id']),
        number: _str(json['number']),
        direction: _str(json['direction'], 'in'),
        paymentDate: _date(json['payment_date']) ?? DateTime.now(),
        partyId: json['party_id'] as String?,
        partyName: json['party_name'] as String?,
        amount: _num(json['amount']),
        chequeDate: _date(json['cheque_date']),
        status: _str(json['cheque_status'], 'pending'),
        referenceNumber: json['reference_number'] as String?,
        isOverdue: _bool(json['is_overdue']),
        daysUntilDue: (json['days_until_due'] as num?)?.toInt(),
      );
}

class ChequeSummary {
  const ChequeSummary({
    this.toDepositCount = 0,
    this.toDepositAmount = 0,
    this.toClearCount = 0,
    this.toClearAmount = 0,
    this.overdueCount = 0,
  });

  final int toDepositCount;
  final num toDepositAmount;
  final int toClearCount;
  final num toClearAmount;
  final int overdueCount;

  bool get isEmpty => toDepositCount == 0 && toClearCount == 0;

  factory ChequeSummary.fromJson(Map<String, dynamic> json) => ChequeSummary(
        toDepositCount: _num(json['to_deposit_count']).toInt(),
        toDepositAmount: _num(json['to_deposit_amount']),
        toClearCount: _num(json['to_clear_count']).toInt(),
        toClearAmount: _num(json['to_clear_amount']),
        overdueCount: _num(json['overdue_count']).toInt(),
      );
}

/// Borrowed money and what is still owed on it.
class Loan {
  const Loan({
    required this.id,
    required this.lenderName,
    required this.startDate,
    this.loanType = 'bank',
    this.principal = 0,
    this.interestRate = 0,
    this.interestType = 'reducing',
    this.tenureMonths = 0,
    this.emiAmount = 0,
    this.outstandingPrincipal = 0,
    this.principalPaid = 0,
    this.interestPaid = 0,
    this.totalPaid = 0,
    this.status = 'active',
    this.instalmentsPaid = 0,
    this.instalmentsLeft = 0,
    this.nextDueDate,
    this.accountNumber,
    this.notes,
  });

  final String id;
  final String lenderName;
  final DateTime startDate;
  final String loanType;
  final num principal;
  final num interestRate;
  final String interestType;
  final int tenureMonths;
  final num emiAmount;
  final num outstandingPrincipal;
  final num principalPaid;
  final num interestPaid;
  final num totalPaid;
  final String status;
  final int instalmentsPaid;
  final int instalmentsLeft;
  final DateTime? nextDueDate;
  final String? accountNumber;
  final String? notes;

  bool get isClosed => status == 'closed';
  bool get isInterestFree => interestType == 'none' || interestRate == 0;

  /// How much of the debt is behind them, 0–1.
  double get progress {
    if (principal <= 0) return 0;
    return (principalPaid / principal).clamp(0, 1).toDouble();
  }

  factory Loan.fromJson(Map<String, dynamic> json) => Loan(
        id: _str(json['id']),
        lenderName: _str(json['lender_name']),
        startDate: _date(json['start_date']) ?? DateTime.now(),
        loanType: _str(json['loan_type'], 'bank'),
        principal: _num(json['principal']),
        interestRate: _num(json['interest_rate']),
        interestType: _str(json['interest_type'], 'reducing'),
        tenureMonths: _num(json['tenure_months']).toInt(),
        emiAmount: _num(json['emi_amount']),
        outstandingPrincipal: _num(json['outstanding_principal']),
        principalPaid: _num(json['principal_paid']),
        interestPaid: _num(json['interest_paid']),
        totalPaid: _num(json['total_paid']),
        status: _str(json['status'], 'active'),
        instalmentsPaid: _num(json['instalments_paid']).toInt(),
        instalmentsLeft: _num(json['instalments_left']).toInt(),
        nextDueDate: _date(json['next_due_date']),
        accountNumber: json['account_number'] as String?,
        notes: json['notes'] as String?,
      );
}

/// One row of a repayment plan.
class LoanInstalment {
  const LoanInstalment({
    required this.number,
    required this.dueDate,
    this.amount = 0,
    this.principal = 0,
    this.interest = 0,
    this.balanceAfter = 0,
  });

  final int number;
  final DateTime dueDate;
  final num amount;
  final num principal;
  final num interest;
  final num balanceAfter;

  factory LoanInstalment.fromJson(Map<String, dynamic> json) => LoanInstalment(
        number: _num(json['number']).toInt(),
        dueDate: _date(json['due_date']) ?? DateTime.now(),
        amount: _num(json['amount']),
        principal: _num(json['principal']),
        interest: _num(json['interest']),
        balanceAfter: _num(json['balance_after']),
      );
}

/// A repayment actually made, split the way the lender applies it.
class LoanPayment {
  const LoanPayment({
    required this.id,
    required this.loanId,
    required this.paymentDate,
    this.amount = 0,
    this.principalComponent = 0,
    this.interestComponent = 0,
    this.balanceAfter = 0,
    this.instalmentNumber,
    this.referenceNumber,
    this.notes,
  });

  final String id;
  final String loanId;
  final DateTime paymentDate;
  final num amount;
  final num principalComponent;
  final num interestComponent;
  final num balanceAfter;
  final int? instalmentNumber;
  final String? referenceNumber;
  final String? notes;

  factory LoanPayment.fromJson(Map<String, dynamic> json) => LoanPayment(
        id: _str(json['id']),
        loanId: _str(json['loan_id']),
        paymentDate: _date(json['payment_date']) ?? DateTime.now(),
        amount: _num(json['amount']),
        principalComponent: _num(json['principal_component']),
        interestComponent: _num(json['interest_component']),
        balanceAfter: _num(json['balance_after']),
        instalmentNumber: (json['instalment_number'] as num?)?.toInt(),
        referenceNumber: json['reference_number'] as String?,
        notes: json['notes'] as String?,
      );
}

class LoanSummary {
  const LoanSummary({
    this.activeCount = 0,
    this.totalBorrowed = 0,
    this.totalOutstanding = 0,
    this.monthlyCommitment = 0,
    this.interestPaid = 0,
  });

  final int activeCount;
  final num totalBorrowed;
  final num totalOutstanding;
  final num monthlyCommitment;
  final num interestPaid;

  factory LoanSummary.fromJson(Map<String, dynamic> json) => LoanSummary(
        activeCount: _num(json['active_count']).toInt(),
        totalBorrowed: _num(json['total_borrowed']),
        totalOutstanding: _num(json['total_outstanding']),
        monthlyCommitment: _num(json['monthly_commitment']),
        interestPaid: _num(json['interest_paid']),
      );
}

// ── pagination ───────────────────────────────────────────────────
class Paged<T> {
  const Paged({
    required this.items,
    this.total = 0,
    this.page = 1,
    this.pages = 1,
    this.hasNext = false,
  });

  final List<T> items;
  final int total;
  final int page;
  final int pages;
  final bool hasNext;

  bool get isEmpty => items.isEmpty;

  factory Paged.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic>) parse,
  ) =>
      Paged(
        items: _maps(json['items']).map(parse).toList(),
        total: _num(json['total']).toInt(),
        page: _num(json['page']).toInt(),
        pages: _num(json['pages']).toInt(),
        hasNext: _bool(json['has_next']),
      );
}

/// Someone who shares access to this shop.
class TeamMember {
  const TeamMember({
    required this.id,
    required this.userId,
    required this.role,
    this.name,
    this.email,
    this.phone,
    this.avatarUrl,
    this.isActive = true,
    this.inviteAcceptedAt,
  });

  final String id;
  final String userId;
  final String role;
  final String? name;
  final String? email;
  final String? phone;
  final String? avatarUrl;
  final bool isActive;
  final DateTime? inviteAcceptedAt;

  /// Invited but has not signed in yet. Until they do, the account is a
  /// placeholder the server created from the email or number.
  bool get isPending => inviteAcceptedAt == null;

  String get displayName =>
      (name?.trim().isNotEmpty ?? false) ? name!.trim() : (email ?? phone ?? 'Team member');

  String get contact => email ?? phone ?? '';

  factory TeamMember.fromJson(Map<String, dynamic> json) => TeamMember(
        id: _str(json['id']),
        userId: _str(json['user_id']),
        role: _str(json['role']),
        name: json['name'] as String?,
        email: json['email'] as String?,
        phone: json['phone'] as String?,
        avatarUrl: json['avatar_url'] as String?,
        isActive: json['is_active'] as bool? ?? true,
        inviteAcceptedAt: _date(json['invite_accepted_at']),
      );
}

/// What each role can do, in the shopkeeper's words rather than permission names.
class TeamRole {
  const TeamRole(this.value, this.label, this.summary);

  final String value;
  final String label;
  final String summary;

  static const all = [
    TeamRole('owner', 'Owner', 'Full control, including deleting the shop'),
    TeamRole('admin', 'Manager', 'Everything except deleting the shop'),
    TeamRole('accountant', 'Accountant', 'Bills, payments, expenses and all reports'),
    TeamRole('salesman', 'Salesman', 'Sales bills, customers and payments received'),
    TeamRole('storekeeper', 'Storekeeper', 'Stock, items and purchase bills'),
    TeamRole('viewer', 'Viewer', 'Can look at everything, change nothing'),
  ];

  static TeamRole of(String value) =>
      all.firstWhere((r) => r.value == value, orElse: () => all.last);
}
