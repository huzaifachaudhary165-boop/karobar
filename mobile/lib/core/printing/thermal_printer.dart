import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';

import '../utils/formatters.dart';

/// Receipt printing on the cheap Bluetooth thermal printers shops actually own.
///
/// These devices speak ESC/POS directly over a serial-profile Bluetooth socket;
/// they have no system print driver, so the OS print dialog cannot see them.
/// That is why this builds the byte stream itself rather than rendering a PDF.
///
/// Everything here is free and works offline — the bill is composed on the
/// phone and pushed to the printer over Bluetooth, with no server involved.
class ThermalPrinter {
  ThermalPrinter._();

  /// Printers people buy come in two widths, and the difference is not
  /// cosmetic: the character grid is 32 columns at 58mm and 48 at 80mm, so a
  /// receipt laid out for one is unreadable on the other.
  static const width58 = PaperSize.mm58;
  static const width80 = PaperSize.mm80;

  static Future<bool> get bluetoothOn => PrintBluetoothThermal.bluetoothEnabled;

  static Future<bool> get permitted =>
      PrintBluetoothThermal.isPermissionBluetoothGranted;

  /// Only *paired* printers. Pairing happens in Android's own Bluetooth
  /// settings, which is where people already know how to do it.
  static Future<List<PrinterDevice>> paired() async {
    final devices = await PrintBluetoothThermal.pairedBluetooths;
    return devices
        .map((d) => PrinterDevice(name: d.name, address: d.macAdress))
        .toList();
  }

  static Future<bool> get connected => PrintBluetoothThermal.connectionStatus;

  static Future<bool> connect(String address) =>
      PrintBluetoothThermal.connect(macPrinterAddress: address);

  static Future<void> disconnect() async => PrintBluetoothThermal.disconnect;

  /// Sends a built receipt. Returns false if the printer dropped the link —
  /// the caller should offer to reconnect rather than silently lose the bill.
  static Future<bool> send(List<int> bytes) =>
      PrintBluetoothThermal.writeBytes(bytes);

  // ── receipts ─────────────────────────────────────────────────────
  /// Lays out a sale receipt.
  ///
  /// Kept deliberately plain: no logo image, no boxes. Thermal paper is cheap
  /// and slow, and a shopkeeper handing over a receipt wants the total legible
  /// from arm's length, not a design.
  static Future<List<int>> receipt({
    required PaperSize paper,
    required String shopName,
    String? shopPhone,
    String? shopAddress,
    required String invoiceNumber,
    required DateTime date,
    String? partyName,
    required List<ReceiptLine> lines,
    required num subtotal,
    num discount = 0,
    num tax = 0,
    required num total,
    num paid = 0,
    String currency = 'Rs',
    String? footer,
  }) async {
    final profile = await CapabilityProfile.load();
    final g = Generator(paper, profile);
    final bytes = <int>[];

    String money(num value) => Fmt.money(value, symbol: '', decimals: false).trim();

    bytes.addAll(g.text(shopName,
        styles: const PosStyles(
          align: PosAlign.center,
          bold: true,
          height: PosTextSize.size2,
          width: PosTextSize.size2,
        )));
    if (shopAddress != null && shopAddress.isNotEmpty) {
      bytes.addAll(g.text(shopAddress, styles: const PosStyles(align: PosAlign.center)));
    }
    if (shopPhone != null && shopPhone.isNotEmpty) {
      bytes.addAll(g.text(shopPhone, styles: const PosStyles(align: PosAlign.center)));
    }

    bytes.addAll(g.hr());
    bytes.addAll(g.row([
      PosColumn(text: invoiceNumber, width: 7, styles: const PosStyles(bold: true)),
      PosColumn(
        text: Fmt.date(date),
        width: 5,
        styles: const PosStyles(align: PosAlign.right),
      ),
    ]));
    if (partyName != null && partyName.isNotEmpty) {
      bytes.addAll(g.text(partyName));
    }
    bytes.addAll(g.hr());

    // Item name gets the space; quantity and money are narrow and right-aligned
    // so the column of figures stays scannable.
    bytes.addAll(g.row([
      PosColumn(text: 'Item', width: 6, styles: const PosStyles(bold: true)),
      PosColumn(text: 'Qty', width: 2, styles: const PosStyles(bold: true, align: PosAlign.right)),
      PosColumn(text: 'Rate', width: 2, styles: const PosStyles(bold: true, align: PosAlign.right)),
      PosColumn(text: 'Amount', width: 2, styles: const PosStyles(bold: true, align: PosAlign.right)),
    ]));

    for (final line in lines) {
      bytes.addAll(g.row([
        PosColumn(text: line.name, width: 6),
        PosColumn(text: Fmt.qty(line.qty), width: 2, styles: const PosStyles(align: PosAlign.right)),
        PosColumn(text: money(line.rate), width: 2, styles: const PosStyles(align: PosAlign.right)),
        PosColumn(text: money(line.amount), width: 2, styles: const PosStyles(align: PosAlign.right)),
      ]));
    }

    bytes.addAll(g.hr());
    void totalRow(String label, num value, {bool emphasise = false}) {
      bytes.addAll(g.row([
        PosColumn(text: label, width: 7, styles: PosStyles(bold: emphasise)),
        PosColumn(
          text: '$currency ${money(value)}',
          width: 5,
          styles: PosStyles(
            align: PosAlign.right,
            bold: emphasise,
            height: emphasise ? PosTextSize.size2 : PosTextSize.size1,
            width: emphasise ? PosTextSize.size2 : PosTextSize.size1,
          ),
        ),
      ]));
    }

    totalRow('Subtotal', subtotal);
    if (discount > 0) totalRow('Discount', -discount);
    if (tax > 0) totalRow('Tax', tax);
    totalRow('TOTAL', total, emphasise: true);
    if (paid > 0) {
      totalRow('Paid', paid);
      final due = total - paid;
      if (due > 0) totalRow('Balance due', due, emphasise: true);
    }

    bytes.addAll(g.hr());
    if (footer != null && footer.isNotEmpty) {
      bytes.addAll(g.text(footer, styles: const PosStyles(align: PosAlign.center)));
    }
    bytes.addAll(g.text('Thank you!',
        styles: const PosStyles(align: PosAlign.center, bold: true)));

    // Feed past the tear bar before cutting, or the last line is left inside.
    bytes.addAll(g.feed(2));
    bytes.addAll(g.cut());
    return bytes;
  }

  /// Item labels for the shelf: name, price and a scannable barcode.
  ///
  /// Printed one per label so a roll can be fed continuously. The barcode is
  /// rendered by the printer's own hardware rather than as an image — it comes
  /// out crisp at any size and takes a fraction of the time to transmit.
  static Future<List<int>> labels({
    required PaperSize paper,
    required List<ItemLabel> items,
    String currency = 'Rs',
  }) async {
    final profile = await CapabilityProfile.load();
    final g = Generator(paper, profile);
    final bytes = <int>[];

    for (final item in items) {
      for (var copy = 0; copy < item.copies; copy++) {
        bytes.addAll(g.text(item.name,
            styles: const PosStyles(align: PosAlign.center, bold: true)));
        bytes.addAll(g.text('$currency ${Fmt.money(item.price, symbol: '', decimals: false).trim()}',
            styles: const PosStyles(
              align: PosAlign.center,
              height: PosTextSize.size2,
              width: PosTextSize.size2,
              bold: true,
            )));

        final code = item.barcode;
        if (code != null && code.isNotEmpty) {
          bytes.addAll(g.barcode(_barcodeFor(code)));
        }
        bytes.addAll(g.feed(1));
      }
    }

    bytes.addAll(g.feed(1));
    bytes.addAll(g.cut());
    return bytes;
  }

  /// Picks the symbology the digits actually satisfy.
  ///
  /// EAN-13 and EAN-8 demand an exact length and a valid check digit; feeding
  /// them anything else makes the printer emit nothing at all, with no error.
  /// CODE39 accepts arbitrary alphanumerics, so it is the safe fallback.
  static Barcode _barcodeFor(String code) {
    final digits = code.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 13 && digits == code) {
      return Barcode.ean13(digits.split(''));
    }
    if (digits.length == 8 && digits == code) {
      return Barcode.ean8(digits.split(''));
    }
    return Barcode.code39(code.toUpperCase().split(''));
  }
}

class PrinterDevice {
  const PrinterDevice({required this.name, required this.address});
  final String name;
  final String address;
}

class ReceiptLine {
  const ReceiptLine({
    required this.name,
    required this.qty,
    required this.rate,
    required this.amount,
  });

  final String name;
  final num qty;
  final num rate;
  final num amount;
}

class ItemLabel {
  const ItemLabel({
    required this.name,
    required this.price,
    this.barcode,
    this.copies = 1,
  });

  final String name;
  final num price;
  final String? barcode;
  final int copies;
}
