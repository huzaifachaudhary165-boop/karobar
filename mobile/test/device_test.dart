import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/device.dart';

/// What this device can do.
///
/// Karobar runs on a phone at the counter, on a Windows machine in the back
/// office, and in a browser on whatever the shop already owns. Some things
/// genuinely do not exist off the phone — the camera plugins and on-device text
/// recognition have no desktop or web implementation — so offering them there
/// is a button that throws.
///
/// Each platform is actually run rather than compared against whatever the test
/// host happens to be, which would only ever assert a tautology. The exception
/// is the browser: `kIsWeb` is a compile-time constant, so it cannot be
/// switched on from a VM test. Its behaviour is asserted as a rule instead —
/// see the last group.
void main() {
  /// Runs [body] as if the app were on [platform].
  void on(TargetPlatform platform, void Function() body) {
    debugDefaultTargetPlatformOverride = platform;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    body();
  }

  group('a phone', () {
    test('is a phone and not a desktop', () {
      on(TargetPlatform.android, () {
        expect(Device.isMobile, isTrue);
        expect(Device.isDesktop, isFalse);
      });
      on(TargetPlatform.iOS, () {
        expect(Device.isMobile, isTrue);
        expect(Device.isDesktop, isFalse);
      });
    });

    test('can scan and can read a bill', () {
      on(TargetPlatform.android, () {
        expect(Device.canScanBarcodes, isTrue);
        expect(Device.canReadBills, isTrue);
      });
    });

    test('thermal printing is Android only in practice', () {
      on(TargetPlatform.android, () => expect(Device.canPrintThermal, isTrue));
      on(TargetPlatform.iOS, () => expect(Device.canPrintThermal, isFalse));
    });
  });

  group('a desktop', () {
    test('is a desktop and not a phone', () {
      for (final platform in [
        TargetPlatform.windows,
        TargetPlatform.linux,
        TargetPlatform.macOS,
      ]) {
        on(platform, () {
          expect(Device.isDesktop, isTrue, reason: '$platform');
          expect(Device.isMobile, isFalse, reason: '$platform');
        });
      }
    });

    test('cannot scan, whatever webcam is plugged into it', () {
      on(TargetPlatform.windows, () {
        expect(Device.canScanBarcodes, isFalse);
        expect(Device.canReadBills, isFalse);
      });
    });

    test('can still listen — the microphone plugin has a Windows build', () {
      on(TargetPlatform.windows, () => expect(Device.canListen, isTrue));
    });

    test('is told where the missing feature can be done instead', () {
      on(TargetPlatform.windows, () {
        // "Nothing happened" and "not on this computer, use your phone" are
        // the same event and completely different answers.
        expect(Device.unavailableHere.toLowerCase(), contains('phone'));
        expect(Device.unavailableHere.endsWith('.'), isTrue);
      });
    });
  });

  group('a browser', () {
    // kIsWeb is a compile-time constant and cannot be switched on here, so
    // these assert the rule: whatever isWeb says, the rest must agree with it.
    test('is neither a phone nor a desktop', () {
      if (!Device.isWeb) return;
      expect(Device.isMobile, isFalse);
      expect(Device.isDesktop, isFalse);
    });

    test('cannot scan, read bills, listen or print thermally', () {
      if (!Device.isWeb) return;
      expect(Device.canScanBarcodes, isFalse);
      expect(Device.canReadBills, isFalse);
      expect(Device.canListen, isFalse);
      expect(Device.canPrintThermal, isFalse);
    });

    test('is sent to the phone app for what it cannot do', () {
      if (!Device.isWeb) return;
      expect(Device.unavailableHere.toLowerCase(), contains('phone'));
    });
  });

  test('a device is never two kinds at once', () {
    for (final platform in TargetPlatform.values) {
      on(platform, () {
        expect(Device.isMobile && Device.isDesktop, isFalse, reason: '$platform');
      });
    }
  });

  test('the reason is always something a shopkeeper can act on', () {
    for (final platform in TargetPlatform.values) {
      on(platform, () {
        expect(Device.unavailableHere, isNotEmpty, reason: '$platform');
        expect(Device.unavailableHere.endsWith('.'), isTrue, reason: '$platform');
      });
    }
  });
}
