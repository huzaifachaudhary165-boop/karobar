import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/device.dart';
import 'package:karobar/core/widgets/handheld_scanner.dart';

/// The USB barcode gun a shop with a laptop actually owns.
///
/// It is not a camera: it registers as a keyboard, types the code as fast as
/// the machine will take it, and presses Enter. That is why it works in a
/// browser and on a desktop where the camera plugin does not exist at all.
///
/// The whole difficulty is telling it apart from a person typing, because both
/// arrive as key events. Speed is the only tell, and getting it wrong in either
/// direction is bad: too eager and a shopkeeper typing a customer's name adds
/// items to the bill; too strict and the scanner does nothing at all.
void main() {
  // A clock the test moves by hand. The whole behaviour is a speed judgement,
  // and a widget test's clock does not move `DateTime.now` — so without this
  // the only way to tell a gun from a person is to sit through real delays.
  late DateTime now;
  late List<String> scanned;

  /// Types [text], leaving [gap] between characters, then Enter if [enter].
  Future<void> type(
    WidgetTester tester,
    String text, {
    Duration gap = const Duration(milliseconds: 8),
    bool enter = true,
  }) async {
    for (final char in text.split('')) {
      now = now.add(gap);
      // Logical key ids for letters are the *lowercase* code points; the test
      // framework cannot find a key code for anything else, which is a limit
      // of the harness rather than of the scanner.
      final key = LogicalKeyboardKey(char.toLowerCase().codeUnitAt(0));
      // Down *and* up: without the release, the same character twice in one
      // code trips the "key is already down" assertion, and half the barcodes
      // in a shop repeat a digit.
      await simulateKeyDownEvent(key, character: char);
      await simulateKeyUpEvent(key);
      await tester.pump();
    }
    if (enter) {
      now = now.add(gap);
      await simulateKeyDownEvent(LogicalKeyboardKey.enter);
      await simulateKeyUpEvent(LogicalKeyboardKey.enter);
    }
    await tester.pump();
  }

  Future<void> pumpListener(WidgetTester tester, {bool enabled = true}) {
    now = DateTime(2026, 1, 1);
    scanned = [];
    return tester.pumpWidget(
      MaterialApp(
        home: HandheldScannerListener(
          enabled: enabled,
          onScan: scanned.add,
          clock: () => now,
          child: const Scaffold(body: SizedBox.expand()),
        ),
      ),
    );
  }

  group('a gun', () {
    testWidgets('a fast burst ending in Enter is a scan', (tester) async {
      await pumpListener(tester);
      await type(tester, '8964000404018');

      expect(scanned, ['8964000404018']);
    });

    testWidgets('two scans in a row are two separate codes', (tester) async {
      // A basket is rung up one item after another without touching anything
      // between, which is the point of a gun.
      await pumpListener(tester);
      await type(tester, '1111111');
      now = now.add(const Duration(milliseconds: 400));
      await type(tester, '2222222');

      expect(scanned, ['1111111', '2222222']);
    });

    testWidgets('letters and digits both come through', (tester) async {
      // Code 128 carries letters, and shops print their own codes that way.
      await pumpListener(tester);
      await type(tester, 'kar0012');

      expect(scanned, ['kar0012']);
    });
  });

  group('a person', () {
    testWidgets('typing slowly is never read as a scan', (tester) async {
      // The bug this speed check exists to prevent: somebody entering a
      // customer's name would otherwise put items on the bill.
      await pumpListener(tester);
      await type(tester, 'ahmed', gap: const Duration(milliseconds: 140));

      expect(scanned, isEmpty);
    });

    testWidgets('pressing Enter on its own does nothing', (tester) async {
      await pumpListener(tester);
      await simulateKeyDownEvent(LogicalKeyboardKey.enter);
      await tester.pump();

      expect(scanned, isEmpty);
    });

    testWidgets('a couple of fast keystrokes are not a barcode', (tester) async {
      // Shorter than any symbology a shop uses — somebody leaning on the
      // keyboard, not a code.
      await pumpListener(tester);
      await type(tester, 'ab');

      expect(scanned, isEmpty);
    });

    testWidgets('a pause mid-burst breaks the code rather than joining it',
        (tester) async {
      await pumpListener(tester);
      await type(tester, '1234', enter: false);
      // Long enough that a person could have done it.
      now = now.add(const Duration(milliseconds: 200));
      await type(tester, '5678');

      // Only the second half, not '12345678' glued together.
      expect(scanned, ['5678']);
    });
  });

  group('when it is switched off', () {
    testWidgets('nothing is picked up at all', (tester) async {
      // A phone has a camera and no gun; listening there would only mean a
      // Bluetooth keyboard could add items nobody asked for.
      await pumpListener(tester, enabled: false);
      await type(tester, '8964000404018');

      expect(scanned, isEmpty);
    });
  });

  group('which machines it is offered on', () {
    test('a browser and a desktop, where there may be no camera', () {
      expect(Device.canUseHandheldScanner, Device.isDesktop || Device.isWeb);
    });

    test('a browser can use its camera as well', () {
      // This was phone-only, which was simply wrong — the scanner plugin
      // drives getUserMedia in a browser and always could.
      expect(Device.canScanBarcodes, Device.isMobile || Device.isWeb);
    });

    test('every machine can scan one way or the other', () {
      expect(
        Device.canScanBarcodes || Device.canUseHandheldScanner,
        isTrue,
        reason: 'a counter with no way to scan at all is the thing to avoid',
      );
    });
  });
}
