import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/printing/thermal_printer.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/device.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Print a bill on a Bluetooth thermal printer.
///
/// The whole flow is: pick a paired printer once, print. The chosen printer and
/// paper width are remembered, so the second bill onwards is a single tap.
Future<void> showPrintSheet(BuildContext context, Voucher voucher) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _PrintSheet(voucher: voucher),
  );
}

class _PrintSheet extends ConsumerStatefulWidget {
  const _PrintSheet({required this.voucher});

  final Voucher voucher;

  @override
  ConsumerState<_PrintSheet> createState() => _PrintSheetState();
}

class _PrintSheetState extends ConsumerState<_PrintSheet> {
  List<PrinterDevice> _printers = const [];
  String? _address;
  bool _is80mm = false;
  bool _busy = false;
  String? _problem;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // Asked before anything touches the plugin. Bluetooth thermal printing is
    // Android-only in practice, so on a computer or in a browser every call
    // below throws a missing-plugin error — which reaches the shopkeeper as a
    // failure with no cause and no alternative. The share sheet on the
    // previous screen already reaches a normal printer from either.
    if (!Device.canPrintThermal) {
      setState(() => _problem =
          'Receipt printing ${Device.unavailableHere.toLowerCase()} '
          'Use Share to send the bill to a printer or on WhatsApp.');
      return;
    }

    setState(() => _busy = true);
    final store = ref.read(tokenStoreProvider);
    try {
      if (!await ThermalPrinter.permitted) {
        setState(() => _problem =
            'Karobar needs Bluetooth permission to reach the printer. '
            'Allow it in your phone settings.');
        return;
      }
      if (!await ThermalPrinter.bluetoothOn) {
        setState(() => _problem = 'Turn Bluetooth on, then try again.');
        return;
      }

      final printers = await ThermalPrinter.paired();
      if (!mounted) return;
      setState(() {
        _printers = printers;
        _address = store.printerAddress ?? (printers.isNotEmpty ? printers.first.address : null);
        _is80mm = store.printerIs80mm;
        _problem = printers.isEmpty
            ? 'No paired printer found. Pair it in your phone\'s Bluetooth '
                'settings first, then come back.'
            : null;
      });
    } catch (error) {
      if (mounted) setState(() => _problem = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _print() async {
    final address = _address;
    if (address == null) return;

    setState(() {
      _busy = true;
      _problem = null;
    });

    try {
      final store = ref.read(tokenStoreProvider);
      await store.setPrinter(address: address, is80mm: _is80mm);

      if (!await ThermalPrinter.connected) {
        final ok = await ThermalPrinter.connect(address);
        if (!ok) {
          setState(() => _problem =
              'Could not reach the printer. Check it is on and in range.');
          return;
        }
      }

      final business = ref.read(sessionProvider).business;
      final voucher = widget.voucher;
      final bytes = await ThermalPrinter.receipt(
        paper: _is80mm ? ThermalPrinter.width80 : ThermalPrinter.width58,
        shopName: business?.name ?? 'Karobar',
        currency: (business?.symbol ?? 'Rs').trim(),
        invoiceNumber: voucher.number,
        date: voucher.voucherDate,
        partyName: voucher.partyName,
        lines: [
          for (final line in voucher.lines)
            ReceiptLine(
              name: line.itemName,
              qty: line.qty,
              rate: line.rate,
              amount: line.total,
            ),
        ],
        subtotal: voucher.subtotal,
        discount: voucher.discountAmount,
        tax: voucher.taxAmount,
        total: voucher.total,
        paid: voucher.paidAmount,
      );

      final sent = await ThermalPrinter.send(bytes);
      if (!mounted) return;

      if (sent) {
        Navigator.pop(context);
        showSuccess(context, 'Sent to the printer.');
      } else {
        setState(() => _problem = 'The printer rejected the receipt. Try reconnecting.');
      }
    } catch (error) {
      if (mounted) setState(() => _problem = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Print receipt', style: theme.textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(
              widget.voucher.number,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 18),

            if (_problem != null)
              AppCard(
                color: AppColors.softTint(AppColors.warning, theme.brightness),
                borderColor: AppColors.warning.withValues(alpha: 0.35),
                child: Row(
                  children: [
                    const Icon(Icons.info_outline, size: 18, color: AppColors.warning),
                    const SizedBox(width: 10),
                    Expanded(child: Text(_problem!, style: const TextStyle(fontSize: 13))),
                  ],
                ),
              )
            else ...[
              Text('Printer', style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              for (final printer in _printers)
                RadioGroup<String>(
                  groupValue: _address,
                  onChanged: (value) => setState(() => _address = value),
                  child: RadioListTile<String>(
                    value: printer.address,
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: Text(printer.name, style: const TextStyle(fontSize: 14)),
                    subtitle: Text(printer.address, style: const TextStyle(fontSize: 11)),
                  ),
                ),
              const SizedBox(height: 14),
              Text('Paper width', style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              // Not cosmetic: 58mm is 32 characters wide and 80mm is 48, so the
              // wrong choice wraps every line of the receipt.
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('58 mm')),
                  ButtonSegment(value: true, label: Text('80 mm')),
                ],
                selected: {_is80mm},
                onSelectionChanged: (value) => setState(() => _is80mm = value.first),
              ),
            ],

            const SizedBox(height: 22),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: _busy ? null : _load,
                    child: Text(context.t('Refresh')),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  flex: 2,
                  child: FilledButton.icon(
                    onPressed: (_busy || _address == null) ? null : _print,
                    icon: _busy
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.print_outlined, size: 18),
                    label: Text(context.t('Print')),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Print shelf labels for one item — name, price and a scannable barcode.
Future<void> showLabelSheet(BuildContext context, WidgetRef ref, Item item) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _LabelSheet(item: item),
  );
}

class _LabelSheet extends ConsumerStatefulWidget {
  const _LabelSheet({required this.item});

  final Item item;

  @override
  ConsumerState<_LabelSheet> createState() => _LabelSheetState();
}

class _LabelSheetState extends ConsumerState<_LabelSheet> {
  int _copies = 1;
  bool _busy = false;
  String? _problem;

  Future<void> _print() async {
    // Same reason as the receipt sheet: the plugin is Android-only, and a
    // missing-plugin error is not something a shopkeeper can act on. The
    // labels screen prints a whole sheet through Share on any machine.
    if (!Device.canPrintThermal) {
      setState(() => _problem =
          'Label printing ${Device.unavailableHere.toLowerCase()} '
          'Use Stock → Barcode labels to print a sheet instead.');
      return;
    }

    setState(() {
      _busy = true;
      _problem = null;
    });

    try {
      final store = ref.read(tokenStoreProvider);
      final address = store.printerAddress;
      if (address == null) {
        setState(() => _problem =
            'Print a receipt once first — that is where the printer is chosen.');
        return;
      }

      if (!await ThermalPrinter.connected) {
        if (!await ThermalPrinter.connect(address)) {
          setState(() => _problem = 'Could not reach the printer.');
          return;
        }
      }

      final bytes = await ThermalPrinter.labels(
        paper: store.printerIs80mm ? PaperSize.mm80 : PaperSize.mm58,
        currency: (ref.read(sessionProvider).business?.symbol ?? 'Rs').trim(),
        items: [
          ItemLabel(
            name: widget.item.name,
            price: widget.item.salePrice,
            barcode: widget.item.barcode,
            copies: _copies,
          ),
        ],
      );

      final sent = await ThermalPrinter.send(bytes);
      if (!mounted) return;
      if (sent) {
        Navigator.pop(context);
        showSuccess(context, '$_copies label${_copies == 1 ? '' : 's'} printed.');
      } else {
        setState(() => _problem = 'The printer rejected the labels.');
      }
    } catch (error) {
      if (mounted) setState(() => _problem = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasBarcode = (widget.item.barcode ?? '').isNotEmpty;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Print labels', style: theme.textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(
              widget.item.name,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 16),

            if (!hasBarcode)
              AppCard(
                color: AppColors.softTint(AppColors.warning, theme.brightness),
                borderColor: AppColors.warning.withValues(alpha: 0.35),
                child: const Text(
                  'This item has no barcode, so the label will show only its '
                  'name and price. Add a barcode to make it scannable.',
                  style: TextStyle(fontSize: 13),
                ),
              ),

            const SizedBox(height: 14),
            Row(
              children: [
                const Text('How many?', style: TextStyle(fontWeight: FontWeight.w600)),
                const Spacer(),
                IconButton(
                  onPressed: _copies > 1 ? () => setState(() => _copies--) : null,
                  icon: const Icon(Icons.remove_circle_outline),
                ),
                Text('$_copies',
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w800)),
                IconButton(
                  onPressed: _copies < 50 ? () => setState(() => _copies++) : null,
                  icon: const Icon(Icons.add_circle_outline),
                ),
              ],
            ),

            if (_problem != null) ...[
              const SizedBox(height: 10),
              Text(_problem!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 13)),
            ],

            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: _busy ? null : _print,
              icon: const Icon(Icons.print_outlined, size: 18),
              label: Text('Print $_copies label${_copies == 1 ? '' : 's'}'),
            ),
          ],
        ),
      ),
    );
  }
}
