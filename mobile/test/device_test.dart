import 'dart:io' show Platform;

import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/device.dart';

/// What this device can do.
///
/// Karobar runs on a phone at the counter and on a Windows machine in the back
/// office. Two things genuinely do not exist on the desktop build — the camera
/// plugins and on-device text recognition have no Windows implementation — so
/// offering them there is a button that throws.
///
/// These run on the host, so they assert the rule rather than one answer.
void main() {
  test('a device is either a phone or a desktop, never both', () {
    expect(Device.isMobile && Device.isDesktop, isFalse);
  });

  test('scanning needs a camera plugin, which only the phone build has', () {
    expect(Device.canScanBarcodes, Device.isMobile);
  });

  test('reading a bill runs on-device and is mobile only', () {
    expect(Device.canReadBills, Device.isMobile);
  });

  test('a desktop cannot scan, whatever webcam is plugged into it', () {
    if (!Device.isDesktop) return;
    expect(Device.canScanBarcodes, isFalse);
    expect(Device.canReadBills, isFalse);
  });

  test('thermal printing is Android only in practice', () {
    expect(Device.canPrintThermal, Platform.isAndroid);
  });

  test('the microphone plugin does have a Windows build', () {
    expect(Device.canListen, isTrue);
  });

  group('what it tells the shopkeeper', () {
    test('the reason is something they can act on', () {
      // "Nothing happened" and "not on this computer, use your phone" are the
      // same event and completely different answers.
      expect(Device.unavailableHere, isNotEmpty);
      expect(Device.unavailableHere.endsWith('.'), isTrue);
    });

    test('a desktop is told where it can be done instead', () {
      if (!Device.isDesktop) return;
      expect(Device.unavailableHere.toLowerCase(), contains('phone'));
    });
  });
}
