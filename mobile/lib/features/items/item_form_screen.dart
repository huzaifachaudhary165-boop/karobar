import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_colors.dart';
import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/barcode_sheet.dart';
import '../../core/widgets/common.dart';
import '../../data/offline_write.dart';
import '../../providers.dart';
import '../invoices/print_sheet.dart';
import '../stock/tracking_card.dart';

/// Create or edit an item, and adjust its stock.
class ItemFormScreen extends ConsumerStatefulWidget {
  const ItemFormScreen({super.key, this.itemId, this.initialBarcode});

  final String? itemId;

  /// Pre-filled when the user scanned a code the shop doesn't have on file yet.
  final String? initialBarcode;

  @override
  ConsumerState<ItemFormScreen> createState() => _ItemFormScreenState();
}

class _ItemFormScreenState extends ConsumerState<ItemFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _salePrice = TextEditingController();
  final _purchasePrice = TextEditingController();
  final _openingStock = TextEditingController();
  final _lowStock = TextEditingController();
  final _taxRate = TextEditingController(text: '0');
  final _barcode = TextEditingController();

  String _unit = 'Pcs';
  bool _isService = false;
  bool _busy = false;
  bool _loading = false;
  num _currentStock = 0;

  // Off unless the shopkeeper asks for it. Most shops sell sugar and soap,
  // where "which batch?" is a question with no answer, and a form that asks it
  // of everything is a form people stop filling in.
  bool _trackBatches = false;
  bool _trackExpiry = false;
  bool _trackSerial = false;

  bool get _isEditing => widget.itemId != null;

  static const _units = ['Pcs', 'Kg', 'g', 'L', 'ml', 'Box', 'Dzn', 'Pkt', 'Bag', 'Btl', 'm', 'Hr'];

  @override
  void initState() {
    super.initState();
    if (_isEditing) {
      _load();
    } else if (widget.initialBarcode != null) {
      _barcode.text = widget.initialBarcode!;
    }
  }

  /// Reloads when the route points at a different item.
  ///
  /// `initState` runs once, and go_router reuses this State when the same route
  /// is opened with new parameters — so opening item B while item A's form was
  /// still on the stack left A's name and prices on screen while the form
  /// belonged to B. Saving then wrote A's figures over B.
  @override
  void didUpdateWidget(ItemFormScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.itemId != oldWidget.itemId) {
      if (_isEditing) {
        _load();
      } else {
        // Went from editing to adding: nothing of the old item may be left
        // behind, or the "new" item is quietly a copy of it.
        setState(() {
          for (final field in [
            _name, _salePrice, _purchasePrice, _openingStock, _lowStock,
            _barcode,
          ]) {
            field.clear();
          }
          _taxRate.text = '0';
          _unit = 'Pcs';
          _isService = false;
          _trackBatches = false;
          _trackExpiry = false;
          _trackSerial = false;
        });
      }
      return;
    }
    if (widget.initialBarcode != oldWidget.initialBarcode &&
        widget.initialBarcode != null) {
      _barcode.text = widget.initialBarcode!;
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _salePrice.dispose();
    _purchasePrice.dispose();
    _openingStock.dispose();
    _lowStock.dispose();
    _taxRate.dispose();
    _barcode.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final item = await ref.read(itemRepositoryProvider).get(widget.itemId!);
      _name.text = item.name;
      _salePrice.text = Fmt.qty(item.salePrice);
      _purchasePrice.text = Fmt.qty(item.purchasePrice);
      _lowStock.text = item.lowStockQty == null ? '' : Fmt.qty(item.lowStockQty);
      _taxRate.text = Fmt.qty(item.taxRate);
      _barcode.text = item.barcode ?? '';
      setState(() {
        _unit = item.unitLabel;
        _isService = item.itemType == 'service';
        _currentStock = item.stockQty;
        _trackBatches = item.trackBatches;
        _trackExpiry = item.trackExpiry;
        _trackSerial = item.trackSerial;
      });
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);

    final openingStock = num.tryParse(_openingStock.text.trim()) ?? 0;
    final purchasePrice = num.tryParse(_purchasePrice.text.trim()) ?? 0;

    final body = <String, dynamic>{
      'name': _name.text.trim(),
      'item_type': _isService ? 'service' : 'product',
      'sale_price': num.tryParse(_salePrice.text.trim()) ?? 0,
      'purchase_price': purchasePrice,
      'unit_label': _unit,
      'tax_rate': num.tryParse(_taxRate.text.trim()) ?? 0,
      if (_barcode.text.trim().isNotEmpty) 'barcode': _barcode.text.trim(),
      if (_lowStock.text.trim().isNotEmpty)
        'low_stock_qty': num.tryParse(_lowStock.text.trim()),
      if (!_isEditing && !_isService) ...{
        'opening_stock': openingStock,
        'opening_stock_value': openingStock * purchasePrice,
      },
      if (!_isService) ...{
        'track_batches': _trackBatches,
        'track_expiry': _trackExpiry,
        'track_serial': _trackSerial,
      },
    };

    try {
      final repository = ref.read(itemRepositoryProvider);
      final result = await saveOrQueue<void>(
        ref,
        entity: 'item',
        data: body,
        operation: _isEditing ? 'update' : 'create',
        serverId: widget.itemId,
        send: () => _isEditing
            ? repository.update(widget.itemId!, body)
            : repository.create(body),
      );
      if (!mounted) return;
      invalidateBusinessData(ref);
      showSuccess(
        context,
        result.queued
            ? queuedMessage
            : (_isEditing ? 'Item updated.' : '${_name.text.trim()} added.'),
      );
      context.pop();
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _adjustStock() async {
    final quantity = TextEditingController();
    final reason = TextEditingController();

    final confirmed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 20,
          bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Adjust stock', style: Theme.of(sheetContext).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(
              'Current: ${Fmt.qty(_currentStock)} $_unit',
              style: Theme.of(sheetContext).textTheme.bodySmall,
            ),
            const SizedBox(height: 18),
            TextField(
              controller: quantity,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
                signed: true,
              ),
              decoration: InputDecoration(
                labelText: context.t('Change'),
                helperText: 'Use a minus sign to reduce, e.g. -3',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: reason,
              decoration: InputDecoration(
                labelText: 'Reason',
                hintText: context.t('Damaged / stock count / wastage'),
              ),
            ),
            const SizedBox(height: 18),
            FilledButton(
              onPressed: () => Navigator.pop(sheetContext, true),
              child: Text(context.t('Apply adjustment')),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );

    if (confirmed != true || !mounted) return;
    final delta = num.tryParse(quantity.text.trim());
    if (delta == null || delta == 0) return;

    try {
      final item = await ref.read(itemRepositoryProvider).adjustStock(
            widget.itemId!,
            delta,
            reason.text.trim().isEmpty ? 'Manual adjustment' : reason.text.trim(),
          );
      if (!mounted) return;
      setState(() => _currentStock = item.stockQty);
      invalidateBusinessData(ref);
      showSuccess(context, 'Stock is now ${Fmt.qty(item.stockQty)} $_unit.');
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('Delete this item?')),
        content: const Text(
          'Items used on past bills cannot be deleted — the history has to stay intact.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(context.t('Cancel')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(context.t('Delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    try {
      await ref.read(itemRepositoryProvider).delete(widget.itemId!);
      if (!mounted) return;
      invalidateBusinessData(ref);
      showSuccess(context, 'Item deleted.');
      context.pop();
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isEditing ? 'Edit item' : 'New item'),
        actions: [
          if (_isEditing) ...[
            // Only for a saved item: a label needs a name and price that exist.
            IconButton(
              icon: const Icon(Icons.label_outline),
              tooltip: 'Print shelf label',
              onPressed: () async {
                final item = await ref.read(itemRepositoryProvider).get(widget.itemId!);
                if (context.mounted) await showLabelSheet(context, ref, item);
              },
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline),
              onPressed: _delete,
            ),
          ],
          TextButton(onPressed: _busy ? null : _save, child: Text(context.t('Save'))),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (_isEditing) ...[
                    AppCard(
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Current stock',
                                  style: Theme.of(context).textTheme.labelMedium,
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  '${Fmt.qty(_currentStock)} $_unit',
                                  style: Theme.of(context)
                                      .textTheme
                                      .titleLarge
                                      ?.copyWith(fontWeight: FontWeight.w800),
                                ),
                              ],
                            ),
                          ),
                          OutlinedButton.icon(
                            onPressed: _adjustStock,
                            style: OutlinedButton.styleFrom(
                              minimumSize: const Size(0, 40),
                            ),
                            icon: const Icon(Icons.tune, size: 16),
                            label: Text(context.t('Adjust')),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('This is a service'),
                    subtitle: const Text('Services have no stock to track'),
                    value: _isService,
                    onChanged: _isEditing ? null : (value) => setState(() => _isService = value),
                  ),
                  const SizedBox(height: 8),
                  TextFormField(
                    controller: _name,
                    textCapitalization: TextCapitalization.words,
                    autofocus: !_isEditing,
                    decoration: const InputDecoration(
                      labelText: 'Item name *',
                      prefixIcon: Icon(Icons.label_outline),
                    ),
                    validator: (value) => (value == null || value.trim().isEmpty)
                        ? 'Item name is required'
                        : null,
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: TextFormField(
                          controller: _salePrice,
                          keyboardType:
                              const TextInputType.numberWithOptions(decimal: true),
                          decoration: const InputDecoration(labelText: 'Sale price *'),
                          validator: (value) {
                            final parsed = num.tryParse(value?.trim() ?? '');
                            return (parsed == null || parsed < 0) ? 'Required' : null;
                          },
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: _purchasePrice,
                          keyboardType:
                              const TextInputType.numberWithOptions(decimal: true),
                          decoration: InputDecoration(labelText: context.t('Cost price')),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          initialValue: _unit,
                          decoration: const InputDecoration(labelText: 'Unit'),
                          items: _units
                              .map((unit) =>
                                  DropdownMenuItem(value: unit, child: Text(unit)))
                              .toList(),
                          onChanged: (value) => setState(() => _unit = value ?? 'Pcs'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: _taxRate,
                          keyboardType:
                              const TextInputType.numberWithOptions(decimal: true),
                          decoration: const InputDecoration(
                            labelText: 'Tax %',
                            suffixText: '%',
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (!_isService) ...[
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        if (!_isEditing)
                          Expanded(
                            child: TextFormField(
                              controller: _openingStock,
                              keyboardType:
                                  const TextInputType.numberWithOptions(decimal: true),
                              decoration: const InputDecoration(
                                labelText: 'Opening stock',
                              ),
                            ),
                          ),
                        if (!_isEditing) const SizedBox(width: 12),
                        Expanded(
                          child: TextFormField(
                            controller: _lowStock,
                            keyboardType:
                                const TextInputType.numberWithOptions(decimal: true),
                            decoration: InputDecoration(
                              labelText: context.t('Alert below'),
                              helperText: 'Low-stock warning',
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: _barcode,
                    decoration: InputDecoration(
                      labelText: context.t('Barcode'),
                      prefixIcon: const Icon(Icons.qr_code_2_outlined),
                      suffixIcon: IconButton(
                        icon: const Icon(Icons.qr_code_scanner),
                        tooltip: 'Scan',
                        onPressed: () async {
                          final code = await scanBarcode(context);
                          if (code != null) setState(() => _barcode.text = code);
                        },
                      ),
                    ),
                  ),
                  if (!_isService) ...[
                    const SizedBox(height: 18),
                    TrackingCard(
                      batches: _trackBatches,
                      expiry: _trackExpiry,
                      serial: _trackSerial,
                      onBatches: (value) => setState(() {
                        _trackBatches = value;
                        // Expiry is a fact about a batch. Without one there is
                        // nothing for the date to belong to.
                        if (!value) _trackExpiry = false;
                      }),
                      onExpiry: (value) => setState(() {
                        _trackExpiry = value;
                        if (value) _trackBatches = true;
                      }),
                      onSerial: (value) => setState(() => _trackSerial = value),
                      // Batches and serials belong to an item that exists.
                      // Offering to add them before the item is saved would
                      // ask what to attach them to.
                      itemId: _isEditing ? widget.itemId : null,
                      itemName: _name.text.trim(),
                    ),
                  ],
                  const SizedBox(height: 26),
                  FilledButton(
                    onPressed: _busy ? null : _save,
                    child: _busy
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(_isEditing ? 'Save changes' : 'Add item'),
                  ),
                ],
              ),
            ),
    );
  }
}
