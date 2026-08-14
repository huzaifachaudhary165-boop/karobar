import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, kIsWeb, TargetPlatform;

/// What this device can actually do.
///
/// Karobar runs at the counter on a phone, in the back office on Windows, and
/// in a browser on whatever the shop already owns. Those are not the same
/// machine. Some things genuinely do not exist off the phone — the camera
/// plugins and on-device text recognition have no desktop or web
/// implementation at all — so a screen that offers them there is a button that
/// throws.
///
/// Checked rather than assumed. A feature that silently does nothing is the
/// same to a shopkeeper as a broken one, and "not here, use your phone" is an
/// answer they can act on.
///
/// Read through `defaultTargetPlatform` rather than `dart:io`, which does not
/// exist in a browser and would stop the web build compiling at all. On the
/// web it reports the browser's own platform — Android on an Android phone —
/// so every check below asks [kIsWeb] first.
abstract final class Device {
  static bool get isWeb => kIsWeb;

  static bool get isMobile =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  static bool get isDesktop =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.windows ||
          defaultTargetPlatform == TargetPlatform.linux ||
          defaultTargetPlatform == TargetPlatform.macOS);

  /// Scanning a barcode needs a camera the scanner plugin can drive. It has no
  /// Windows implementation, so on the desktop this is false even on a laptop
  /// that has a webcam.
  static bool get canScanBarcodes => isMobile;

  /// Reading a supplier's bill from a photo runs on-device and is Android and
  /// iOS only.
  static bool get canReadBills => isMobile;

  /// Speaking to the assistant needs the microphone plugin, which has a
  /// Windows implementation but not a web one.
  static bool get canListen => !kIsWeb;

  /// Bluetooth thermal printing is Android-only in practice.
  static bool get canPrintThermal =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  /// A one-line reason, for a screen that has to explain itself.
  ///
  /// Names where it *can* be done. "Nothing happened" and "not in the browser,
  /// use the app on your phone" are the same event and completely different
  /// answers, and only one of them is something a shopkeeper can act on.
  static String get unavailableHere {
    if (kIsWeb) {
      return 'Not available in the browser — use the Karobar app on your phone.';
    }
    if (isDesktop) {
      return 'Not available on this computer — use the app on your phone.';
    }
    return 'Not available on this device.';
  }
}
