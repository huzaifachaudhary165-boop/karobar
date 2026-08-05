import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/network/api_exception.dart';
import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/barcode_sheet.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../data/offline_write.dart';
import '../../providers.dart';

/// Build a bill: pick a party, add lines, optionally take payment.
///
/// Totals are computed locally for instant feedback; the server recomputes them
/// authoritatively on save, so the two can never silently diverge.
class InvoiceFormScreen extends ConsumerStatefulWidget {
  const InvoiceFormScreen({super.key, this.voucherType = 'sale', this.partyId});

  final String voucherType;
  final String? partyId;

  @override
  ConsumerState<InvoiceFormScreen> createState() => _InvoiceFormScreenState();
}

class _LineDraft {
  _LineDraft({required this.item, this.qty = 1, num? rate, num? taxRate})
      : rate = rate ?? item.salePrice,
        taxRate = taxRate ?? item.taxRate;

  final Item item;
  num qty;
  num rate;
  num taxRate;
  num discountPercent = 0;

  num get gross => qty * rate;
  num get discount => gross * discountPercent / 100;
  num get taxable => gross - discount;
  num get tax => taxable * taxRate / 100;
  num get total => taxable + tax;
}

class _InvoiceFormScreenState extends ConsumerState<InvoiceFormScreen> {
  final _lines = <_LineDraft>[];
  final _notes = TextEditingController();
  final _paidAmount = TextEditingController();

  Party? _party;
  DateTime _date = DateTime.now();
  String _paymentMode = 'cash';
  bool _busy = false;

  bool get _isPurchase =>
      widget.voucherType == 'purchase' || widget.voucherType == 'purchase_return';

  String get _title => switch (widget.voucherType) {
        'purchase' => 'New purchase bill',
        'quotation' => 'New quotation',
        'sale_return' => 'Sale return',
        'purchase_return' => 'Purchase return',
        _ => 'New sale invoice',
      };

  num get _subtotal => _lines.fold<num>(0, (sum, line) => sum + line.gross);
  num get _discount => _lines.fold<num>(0, (sum, line) => sum + line.discount);
  num get _tax => _lines.fold<num>(0, (sum, line) => sum + line.tax);
  num get _total => _lines.fold<num>(0, (sum, line) => sum + line.total);

  @override
  void initState() {
    super.initState();
    if (widget.partyId != null) _loadParty(widget.partyId!);
  }

  @override
  void dispose() {
    _notes.dispose();
    _paidAmount.dispose();
    super.dispose();
  }

  Future<void> _loadParty(String id) async {
    try {
      final party = await ref.read(partyRepositoryProvider).get(id);
      if (mounted) setState(() => _party = party);
    } catch (_) {
      // A missing party just leaves the picker empty.
    }
  }

  Future<void> _pickParty() async {
    final party = await showModalBottomSheet<Party>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _PartyPicker(isSupplier: _isPurchase),
    );
    if (party != null) setState(() => _party = party);
  }

  Future<void> _addLine() async {
    final item = await showModalBottomSheet<Item>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _ItemPicker(),
    );
    if (item != null) _addItem(item);
  }

  /// Scan straight onto the bill. The sheet reopens after each code so a whole
  /// basket can be rung up without tapping between scans.
  Future<void> _scanLine() async {
    while (mounted) {
      final code = await scanBarcode(context);
      if (code == null || !mounted) return;

      try {
        final item = await ref.read(itemRepositoryProvider).byBarcode(code);
        if (!mounted) return;
        _addItem(item);
      } on ApiException catch (error) {
        if (!mounted) return;
        showError(
          context,
          error.isNotFound ? 'No item has the code $code.' : error,
        );
        return;
      }
    }
  }

  void _addItem(Item item) {
    setState(() {
      // Adding the same item twice bumps the quantity — a shopkeeper scanning a
      // basket expects that, not two identical lines.
      final existing = _lines.indexWhere((line) => line.item.id == item.id);
      if (existing >= 0) {
        _lines[existing].qty += 1;
      } else {
        _lines.add(
          _LineDraft(
            item: item,
            qty: 1,
            rate: _isPurchase ? item.purchasePrice : item.salePrice,
          ),
        );
      }
    });
  }

  Future<void> _save() async {
    if (_lines.isEmpty) {
      showError(context, 'Add at least one item to the bill.');
      return;
    }
    if (_party == null && widget.voucherType != 'quotation') {
      showError(context, 'Choose a ${_isPurchase ? 'supplier' : 'customer'} first.');
      return;
    }

    setState(() => _busy = true);
    final paid = num.tryParse(_paidAmount.text.trim());

    final body = <String, dynamic>{
      'voucher_type': widget.voucherType,
      if (_party != null) 'party_id': _party!.id,
      'voucher_date': Fmt.iso(_date),
      'lines': _lines
          .map((line) => {
                'item_id': line.item.id,
                'item_name': line.item.name,
                'qty': line.qty,
                'rate': line.rate,
                'tax_rate': line.taxRate,
                if (line.discountPercent > 0) ...{
                  'discount_type': 'percent',
                  'discount_value': line.discountPercent,
                },
              })
          .toList(),
      if (_notes.text.trim().isNotEmpty) 'notes': _notes.text.trim(),
      if (paid != null && paid > 0)
        'payment': {'amount': paid, 'mode': _paymentMode},
    };

    try {
      final result = await saveOrQueue<Voucher>(
        ref,
        entity: 'voucher',
        data: body,
        send: () => ref.read(voucherRepositoryProvider).create(body),
      );
      if (!mounted) return;
      invalidateBusinessData(ref);

      // A queued bill has no number yet — the server assigns it on upload, so
      // there is no detail page to open.
      if (result.queued) {
        showSuccess(context, queuedMessage);
        context.pop();
        return;
      }

      final voucher = result.value!;
      showSuccess(context, '${voucher.number} created.');
      context.pushReplacementNamed(
        Routes.invoiceDetail,
        pathParameters: {'id': voucher.id},
      );
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(_title)),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
              children: [
                AppCard(
                  onTap: _pickParty,
                  child: Row(
                    children: [
                      if (_party != null)
                        NameAvatar(_party!.name, size: 40)
                      else
                        Container(
                          width: 40,
                          height: 40,
                          decoration: BoxDecoration(
                            color: theme.colorScheme.surfaceContainerHighest,
                            borderRadius: BorderRadius.circular(13),
                          ),
                          child: Icon(
                            _isPurchase
                                ? Icons.local_shipping_outlined
                                : Icons.person_outline,
                            size: 20,
                          ),
                        ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              _party?.name ??
                                  'Choose a ${_isPurchase ? 'supplier' : 'customer'}',
                              style: theme.textTheme.titleSmall?.copyWith(
                                fontWeight: FontWeight.w700,
                                color: _party == null
                                    ? theme.colorScheme.onSurfaceVariant
                                    : null,
                              ),
                            ),
                            if (_party != null && _party!.balance != 0)
                              Text(
                                '${_party!.owesUs ? 'Owes you' : 'You owe'} '
                                '${Fmt.money(_party!.balance.abs(), symbol: symbol, decimals: false)}',
                                style: theme.textTheme.labelSmall?.copyWith(
                                  color: AppColors.forBalance(_party!.balance),
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                          ],
                        ),
                      ),
                      const Icon(Icons.chevron_right),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                AppCard(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                  child: Row(
                    children: [
                      const Icon(Icons.event_outlined, size: 19),
                      const SizedBox(width: 12),
                      Expanded(child: Text(Fmt.date(_date))),
                      TextButton(
                        onPressed: () async {
                          final picked = await showDatePicker(
                            context: context,
                            initialDate: _date,
                            firstDate: DateTime(2020),
                            lastDate: DateTime.now().add(const Duration(days: 365)),
                          );
                          if (picked != null) setState(() => _date = picked);
                        },
                        child: Text(context.t('Change')),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                Row(
                  children: [
                    Text('Items', style: theme.textTheme.titleMedium),
                    const Spacer(),
                    IconButton(
                      onPressed: _scanLine,
                      icon: const Icon(Icons.qr_code_scanner, size: 20),
                      tooltip: 'Scan barcodes onto the bill',
                      visualDensity: VisualDensity.compact,
                    ),
                    TextButton.icon(
                      onPressed: _addLine,
                      icon: const Icon(Icons.add, size: 18),
                      label: Text(context.t('Add item')),
                    ),
                  ],
                ),
                if (_lines.isEmpty)
                  AppCard(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 22),
                      child: Column(
                        children: [
                          Icon(
                            Icons.add_shopping_cart_outlined,
                            size: 30,
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'No items yet',
                            style: theme.textTheme.bodyMedium
                                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                          ),
                          const SizedBox(height: 10),
                          OutlinedButton(
                            onPressed: _addLine,
                            style: OutlinedButton.styleFrom(minimumSize: const Size(160, 42)),
                            child: Text(context.t('Add the first item')),
                          ),
                        ],
                      ),
                    ),
                  )
                else
                  ...List.generate(
                    _lines.length,
                    (index) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: _LineCard(
                        line: _lines[index],
                        symbol: symbol,
                        onChanged: () => setState(() {}),
                        onRemove: () => setState(() => _lines.removeAt(index)),
                      ),
                    ),
                  ),

                if (_lines.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  AppCard(
                    child: Column(
                      children: [
                        _TotalRow(label: 'Subtotal', value: _subtotal, symbol: symbol),
                        if (_discount > 0)
                          _TotalRow(
                            label: 'Discount',
                            value: -_discount,
                            symbol: symbol,
                          ),
                        if (_tax > 0)
                          _TotalRow(label: 'Tax', value: _tax, symbol: symbol),
                        const Divider(height: 20),
                        _TotalRow(
                          label: 'Total',
                          value: _total,
                          symbol: symbol,
                          emphasise: true,
                        ),
                      ],
                    ),
                  ),
                  if (widget.voucherType != 'quotation') ...[
                    const SizedBox(height: 14),
                    AppCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Payment now', style: theme.textTheme.titleSmall),
                          const SizedBox(height: 10),
                          Row(
                            children: [
                              Expanded(
                                child: TextField(
                                  controller: _paidAmount,
                                  keyboardType: const TextInputType.numberWithOptions(
                                    decimal: true,
                                  ),
                                  decoration: InputDecoration(
                                    labelText: context.t('Amount received'),
                                    prefixText: symbol,
                                    isDense: true,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 10),
                              TextButton(
                                onPressed: () => setState(
                                  () => _paidAmount.text = _total.toStringAsFixed(0),
                                ),
                                child: Text(context.t('Full')),
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Wrap(
                            spacing: 8,
                            children: [
                              for (final mode in ['cash', 'bank', 'easypaisa', 'jazzcash'])
                                ChoiceChip(
                                  label: Text(Fmt.titleCase(mode)),
                                  selected: _paymentMode == mode,
                                  showCheckmark: false,
                                  onSelected: (_) => setState(() => _paymentMode = mode),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 14),
                  TextField(
                    controller: _notes,
                    maxLines: 2,
                    decoration: InputDecoration(labelText: context.t('Notes (optional)')),
                  ),
                ],
                const SizedBox(height: 90),
              ],
            ),
          ),
        ],
      ),
      bottomSheet: Container(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
        decoration: BoxDecoration(
          color: theme.colorScheme.surface,
          border: Border(top: BorderSide(color: theme.colorScheme.outline)),
        ),
        child: SafeArea(
          top: false,
          child: Row(
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('Total', style: theme.textTheme.labelMedium),
                  MoneyText(
                    _total,
                    symbol: symbol,
                    decimals: false,
                    style: theme.textTheme.headlineSmall
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ],
              ),
              const SizedBox(width: 16),
              Expanded(
                child: FilledButton(
                  onPressed: _busy || _lines.isEmpty ? null : _save,
                  child: _busy
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Text('Save bill'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _LineCard extends StatelessWidget {
  const _LineCard({
    required this.line,
    required this.symbol,
    required this.onChanged,
    required this.onRemove,
  });

  final _LineDraft line;
  final String symbol;
  final VoidCallback onChanged;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppCard(
      padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  line.item.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close, size: 18),
                visualDensity: VisualDensity.compact,
                onPressed: onRemove,
              ),
            ],
          ),
          Row(
            children: [
              _Stepper(
                value: line.qty,
                unit: line.item.unitLabel,
                onChanged: (value) {
                  line.qty = value;
                  onChanged();
                },
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextFormField(
                  initialValue: Fmt.qty(line.rate),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  textAlign: TextAlign.right,
                  decoration: InputDecoration(
                    isDense: true,
                    prefixText: symbol,
                    contentPadding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                  ),
                  onChanged: (value) {
                    line.rate = num.tryParse(value) ?? line.rate;
                    onChanged();
                  },
                ),
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 84,
                child: Text(
                  Fmt.money(line.total, symbol: symbol, decimals: false),
                  textAlign: TextAlign.right,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(width: 8),
            ],
          ),
        ],
      ),
    );
  }
}

class _Stepper extends StatelessWidget {
  const _Stepper({required this.value, required this.unit, required this.onChanged});

  final num value;
  final String unit;
  final ValueChanged<num> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outline),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          InkWell(
            onTap: value > 1 ? () => onChanged(value - 1) : null,
            child: const Padding(
              padding: EdgeInsets.all(7),
              child: Icon(Icons.remove, size: 15),
            ),
          ),
          SizedBox(
            width: 34,
            child: Text(
              Fmt.qty(value),
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
            ),
          ),
          InkWell(
            onTap: () => onChanged(value + 1),
            child: const Padding(
              padding: EdgeInsets.all(7),
              child: Icon(Icons.add, size: 15),
            ),
          ),
        ],
      ),
    );
  }
}

class _TotalRow extends StatelessWidget {
  const _TotalRow({
    required this.label,
    required this.value,
    required this.symbol,
    this.emphasise = false,
  });

  final String label;
  final num value;
  final String symbol;
  final bool emphasise;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: emphasise
                ? theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)
                : theme.textTheme.bodyMedium,
          ),
          MoneyText(
            value,
            symbol: symbol,
            style: emphasise
                ? theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    color: AppColors.primary,
                  )
                : theme.textTheme.bodyMedium,
          ),
        ],
      ),
    );
  }
}

class _PartyPicker extends ConsumerStatefulWidget {
  const _PartyPicker({required this.isSupplier});

  final bool isSupplier;

  @override
  ConsumerState<_PartyPicker> createState() => _PartyPickerState();
}

class _PartyPickerState extends ConsumerState<_PartyPicker> {
  final _controller = TextEditingController();
  List<Party> _results = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load('');
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _load(String query) async {
    setState(() => _loading = true);
    try {
      final page = await ref.read(partyRepositoryProvider).list(
            search: query.isEmpty ? null : query,
            partyType: widget.isSupplier ? 'supplier' : 'customer',
            size: 40,
          );
      if (mounted) setState(() => _results = page.items);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Creates a party without leaving the bill.
  ///
  /// The only way to add one from here was a button that navigated to the party
  /// form — which replaces this route, so the half-written bill was gone. A
  /// customer walking in who is not on file is the most ordinary thing there
  /// is; it should not cost the shopkeeper the invoice they were typing.
  ///
  /// Name only, because that is all that is needed to bill someone. Everything
  /// else can be filled in later from the party's own screen.
  Future<void> _quickAdd() async {
    final controller = TextEditingController(text: _controller.text.trim());
    final label = widget.isSupplier ? 'supplier' : 'customer';

    final name = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('${dialogContext.t('New')} ${dialogContext.t(label)}'),
        content: TextField(
          controller: controller,
          autofocus: true,
          textCapitalization: TextCapitalization.words,
          decoration: InputDecoration(labelText: dialogContext.t('Name')),
          onSubmitted: (value) => Navigator.pop(dialogContext, value.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: Text(dialogContext.t('Cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, controller.text.trim()),
            child: Text(dialogContext.t('Add')),
          ),
        ],
      ),
    );

    if (name == null || name.isEmpty || !mounted) return;

    try {
      final party = await ref.read(partyRepositoryProvider).create({
        'name': name,
        'party_type': widget.isSupplier ? 'supplier' : 'customer',
      });
      if (!mounted) return;
      // Straight back to the bill with them already chosen.
      Navigator.pop(context, party);
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;

    return DraggableScrollableSheet(
      initialChildSize: 0.8,
      expand: false,
      builder: (_, scrollController) => Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    autofocus: true,
                    onChanged: _load,
                    decoration: InputDecoration(
                      hintText: 'Search ${widget.isSupplier ? 'suppliers' : 'customers'}',
                      prefixIcon: const Icon(Icons.search),
                      isDense: true,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.person_add_outlined),
                  tooltip: context.t('Add new'),
                  onPressed: _quickAdd,
                ),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _results.isEmpty
                    ? EmptyState(
                        title: context.t('No matches'),
                        message: _controller.text.trim().isEmpty
                            ? context.t('Add whoever you are billing.')
                            : '${context.t('Nobody here by that name.')} '
                                '${context.t('Add them and carry on with the bill.')}',
                        icon: Icons.search_off,
                        // Telling someone to add a party without giving them a
                        // way to do it is where this dead-ended.
                        actionLabel: widget.isSupplier
                            ? context.t('Add supplier')
                            : context.t('Add customer'),
                        onAction: _quickAdd,
                      )
                    : ListView.builder(
                        controller: scrollController,
                        itemCount: _results.length,
                        itemBuilder: (_, index) {
                          final party = _results[index];
                          return ListTile(
                            leading: NameAvatar(party.name, size: 38),
                            title: Text(party.name),
                            subtitle: party.balance == 0
                                ? Text(party.phone ?? '')
                                : Text(
                                    '${party.owesUs ? 'Owes' : 'You owe'} '
                                    '${Fmt.money(party.balance.abs(), symbol: symbol, decimals: false)}',
                                    style: TextStyle(
                                      color: AppColors.forBalance(party.balance),
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                            onTap: () => Navigator.pop(context, party),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}

class _ItemPicker extends ConsumerStatefulWidget {
  const _ItemPicker();

  @override
  ConsumerState<_ItemPicker> createState() => _ItemPickerState();
}

class _ItemPickerState extends ConsumerState<_ItemPicker> {
  final _controller = TextEditingController();
  List<Item> _results = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load('');
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _load(String query) async {
    setState(() => _loading = true);
    try {
      final page = await ref.read(itemRepositoryProvider).list(
            search: query.isEmpty ? null : query,
            size: 40,
          );
      if (mounted) setState(() => _results = page.items);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Adds an item without abandoning the bill.
  ///
  /// Same dead end as the party picker: the only route out was a button that
  /// navigated to the item form, replacing this one and losing the invoice
  /// being written. Selling something not yet on file is routine.
  ///
  /// Name and selling price only. Everything else — stock, tax, purchase price
  /// — can be filled in from the item's own screen afterwards.
  Future<void> _quickAdd() async {
    final nameController = TextEditingController(text: _controller.text.trim());
    final priceController = TextEditingController();

    final created = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(dialogContext.t('New item')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              autofocus: true,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(labelText: dialogContext.t('Item name')),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: priceController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[\d.]')),
              ],
              decoration: InputDecoration(labelText: dialogContext.t('Selling price')),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(dialogContext.t('Cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(dialogContext.t('Add')),
          ),
        ],
      ),
    );

    final name = nameController.text.trim();
    if (created != true || name.isEmpty || !mounted) return;

    try {
      final item = await ref.read(itemRepositoryProvider).create({
        'name': name,
        'sale_price': num.tryParse(priceController.text.trim()) ?? 0,
      });
      if (!mounted) return;
      Navigator.pop(context, item);
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;

    return DraggableScrollableSheet(
      initialChildSize: 0.8,
      expand: false,
      builder: (_, scrollController) => Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    autofocus: true,
                    onChanged: _load,
                    decoration: const InputDecoration(
                      hintText: 'Search items',
                      prefixIcon: Icon(Icons.search),
                      isDense: true,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.add_box_outlined),
                  tooltip: context.t('Add new item'),
                  onPressed: _quickAdd,
                ),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _results.isEmpty
                    ? EmptyState(
                        title: context.t('No items found'),
                        message: _controller.text.trim().isEmpty
                            ? context.t('Add what you are selling.')
                            : '${context.t('Nothing here by that name.')} '
                                '${context.t('Add it and carry on with the bill.')}',
                        icon: Icons.search_off,
                        actionLabel: context.t('Add item'),
                        onAction: _quickAdd,
                      )
                    : ListView.builder(
                        controller: scrollController,
                        itemCount: _results.length,
                        itemBuilder: (_, index) {
                          final item = _results[index];
                          return ListTile(
                            title: Text(item.name),
                            subtitle: Text(
                              '${item.stockLabel} · '
                              '${Fmt.money(item.salePrice, symbol: symbol, decimals: false)}',
                            ),
                            trailing: item.isOutOfStock
                                ? const StatusChip('overdue', label: 'Out', dense: true)
                                : item.isLowStock
                                    ? const StatusChip('partial', label: 'Low', dense: true)
                                    : null,
                            onTap: () => Navigator.pop(context, item),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}
