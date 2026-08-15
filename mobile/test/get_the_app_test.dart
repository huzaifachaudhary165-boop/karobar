import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/device.dart';
import 'package:karobar/core/widgets/get_the_app.dart';

/// Offering the phone app, and where the file comes from.
///
/// Three things exist on a phone and cannot exist in a browser: scanning a
/// barcode with the camera, reading a supplier bill from a photo, and printing
/// on a Bluetooth thermal printer. The app said so and stopped there, which
/// leaves a shopkeeper knowing what they are missing and no way to get it.
void main() {
  group('where the file comes from', () {
    test('both builds are named and pointed at the latest release', () {
      // `latest/download` rather than a pinned tag: cutting a new release then
      // has to update the app as well, and the download that everybody has
      // already been sent goes stale silently.
      for (final url in [PhoneApp.universal, PhoneApp.arm64]) {
        expect(url, startsWith('https://'));
        expect(url, contains('/releases/latest/download/'));
        expect(url, endsWith('.apk'));
      }
    });

    test('the two downloads are different files', () {
      expect(PhoneApp.universal, isNot(PhoneApp.arm64));
    });

    test('the sizes shown are the ones a shopkeeper decides on', () {
      // Named in megabytes because that is the number that matters on a
      // shop's connection. "arm64-v8a" is not a choice anybody at a counter
      // can make.
      expect(PhoneApp.universalSize, contains('MB'));
      expect(PhoneApp.arm64Size, contains('MB'));
    });
  });

  group('who sees it', () {
    testWidgets('nothing at all outside a browser', (tester) async {
      // Tests run on the VM, so this is the phone-and-desktop case: offering
      // somebody the app they are already using is how a screen loses their
      // trust.
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: GetTheApp())),
      );

      if (Device.isWeb) return;
      expect(find.byType(FilledButton), findsNothing);
      expect(find.textContaining('Download'), findsNothing);
    });

    testWidgets('the compact form is equally silent', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: GetTheApp(compact: true))),
      );

      if (Device.isWeb) return;
      expect(find.byType(TextButton), findsNothing);
    });

    testWidgets('a reason can be given without changing whether it shows',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: GetTheApp(reason: 'Scanning needs a camera.')),
        ),
      );

      if (Device.isWeb) return;
      expect(find.textContaining('Scanning'), findsNothing);
    });
  });
}
