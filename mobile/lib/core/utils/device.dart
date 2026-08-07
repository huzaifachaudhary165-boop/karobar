import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;

/// What this device can actually do.
///
/// Karobar runs on a phone at the counter and on a Windows machine in the back
/// office, and those are not the same machine. Two things genuinely do not
/// exist on the desktop build — the camera plugins and on-device text
/// recognition have no Windows implementation at all — so a screen that offers
/// them there is a button that throws.
///
/// Checked rather than assumed. A feature that silently does nothing is the
/// same to a shopkeeper as a broken one, and "not on this computer, use your
/// phone" is an answer they can act on.
abstract final class Device {
  static bool get isMobile => !kIsWeb && (Platform.isAndroid || Platform.isIOS);

  static bool get isDesktop =>
      !kIsWeb && (Platform.isWindows || Platform.isLinux || Platform.isMacOS);

  /// Scanning a barcode needs a camera the scanner plugin can drive. It has no
  /// Windows implementation, so on the desktop this is false even on a laptop
  /// that has a webcam.
  static bool get canScanBarcodes => isMobile;

  /// Reading a supplier's bill from a photo runs on-device and is Android and
  /// iOS only.
  static bool get canReadBills => isMobile;

  /// Speaking to the assistant needs the microphone plugin, which does have a
  /// Windows implementation.
  static bool get canListen => !kIsWeb;

  /// Bluetooth thermal printing is Android-only in practice.
  static bool get canPrintThermal => !kIsWeb && Platform.isAndroid;

  /// A one-line reason, for a screen that has to explain itself.
  static String get unavailableHere => isDesktop
      ? 'Not available on this computer — use the app on your phone.'
      : 'Not available on this device.';
}
