import 'package:flutter/material.dart';

/// The trade documents a shop can raise, and what each one actually does.
///
/// One place rather than scattered `switch` statements: a document's title, the
/// side of the trade it sits on, whether it takes payment and whether it moves
/// stock all have to agree, and they only stayed in step here.
///
/// The three properties that matter, and why:
///
/// * [isPurchase] picks suppliers rather than customers, and defaults each line
///   to the buying price. A purchase order drafted at retail bills the shop for
///   its own margin.
/// * [takesPayment] is false for every promise. Nobody pays against an order —
///   the money comes with the invoice it becomes — and showing a "paid now"
///   field on one invites an entry that has nowhere to go.
/// * [movesStock] is true only for the delivery challan among the promises,
///   because the goods have physically left the shop whether or not a bill
///   has been raised yet.
enum DocumentType {
  sale(
    key: 'sale',
    label: 'Sale',
    plural: 'Sales',
    newLabel: 'New sale invoice',
    icon: Icons.receipt_long_outlined,
    takesPayment: true,
    movesStock: true,
  ),
  purchase(
    key: 'purchase',
    label: 'Purchase',
    plural: 'Purchases',
    newLabel: 'New purchase bill',
    icon: Icons.shopping_bag_outlined,
    isPurchase: true,
    takesPayment: true,
    movesStock: true,
  ),
  quotation(
    key: 'quotation',
    label: 'Quotation',
    plural: 'Quotations',
    newLabel: 'New quotation',
    icon: Icons.request_quote_outlined,
    needsParty: false,
  ),
  proforma(
    key: 'proforma',
    label: 'Proforma',
    plural: 'Proformas',
    newLabel: 'New proforma invoice',
    icon: Icons.description_outlined,
  ),
  saleOrder(
    key: 'sale_order',
    label: 'Sale order',
    plural: 'Sale orders',
    newLabel: 'New sale order',
    icon: Icons.assignment_turned_in_outlined,
  ),
  purchaseOrder(
    key: 'purchase_order',
    label: 'Purchase order',
    plural: 'Purchase orders',
    newLabel: 'New purchase order',
    icon: Icons.assignment_outlined,
    isPurchase: true,
  ),
  deliveryChallan(
    key: 'delivery_challan',
    label: 'Delivery challan',
    plural: 'Delivery challans',
    newLabel: 'New delivery challan',
    icon: Icons.local_shipping_outlined,
    movesStock: true,
  ),
  saleReturn(
    key: 'sale_return',
    label: 'Sale return',
    plural: 'Sale returns',
    newLabel: 'Sale return',
    icon: Icons.assignment_return_outlined,
    takesPayment: true,
    movesStock: true,
  ),
  purchaseReturn(
    key: 'purchase_return',
    label: 'Purchase return',
    plural: 'Purchase returns',
    newLabel: 'Purchase return',
    icon: Icons.keyboard_return,
    isPurchase: true,
    takesPayment: true,
    movesStock: true,
  );

  const DocumentType({
    required this.key,
    required this.label,
    required this.plural,
    required this.newLabel,
    required this.icon,
    this.isPurchase = false,
    this.takesPayment = false,
    this.movesStock = false,
    this.needsParty = true,
  });

  /// The `voucher_type` the API uses.
  final String key;
  final String label;
  final String plural;
  final String newLabel;
  final IconData icon;

  /// Buying side of the trade: pick a supplier, price from purchase_price.
  final bool isPurchase;

  /// Whether money can change hands on this document.
  final bool takesPayment;

  /// Whether raising it changes what is on the shelf.
  final bool movesStock;

  /// A quotation can be drafted for a walk-in nobody has named yet.
  final bool needsParty;

  /// The tabs on the documents screen, in the order a shop uses them.
  static const listed = [sale, purchase, quotation, saleOrder, purchaseOrder,
      proforma, deliveryChallan];

  /// Looks up a type, falling back to a sale.
  ///
  /// Never throws: an unknown key reaches here from a deep link or an older
  /// build's saved state, and a crash on the documents tab is a far worse
  /// answer than showing sales.
  static DocumentType of(String? key) => values.firstWhere(
        (type) => type.key == key,
        orElse: () => sale,
      );

  /// Whether this document is one of the promises rather than a transaction.
  bool get isPromise => !takesPayment && this != saleReturn && this != purchaseReturn;

  @override
  String toString() => key;
}
