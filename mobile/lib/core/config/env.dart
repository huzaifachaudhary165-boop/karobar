import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, kIsWeb, TargetPlatform;

/// Build-time configuration.
///
/// Override at build time:
///   flutter run --dart-define=API_BASE_URL=https://api.karobar.app
abstract final class Env {
  static const String appName = 'Karobar';
  static const String appNameUrdu = 'کاروبار';
  static const String version = '1.0.0';

  /// Which build this is, shown in Settings.
  ///
  /// Exists because "is the fix in the APK you are running?" turned into
  /// guesswork more than once — a bug reported as unfixed and a bug fixed in a
  /// build nobody had installed look exactly alike from here. Passed in at
  /// build time:
  ///
  ///   flutter build apk --dart-define=BUILD_STAMP=$(date +%Y-%m-%d-%H%M)
  static const String buildStamp =
      String.fromEnvironment('BUILD_STAMP', defaultValue: 'dev');

  static const String _apiOverride = String.fromEnvironment('API_BASE_URL');

  /// The emulator loopback differs per platform, which is the usual first-run trap.
  ///
  /// Asks [kIsWeb] before the platform, because a browser reports itself as
  /// Android on an Android phone and would then be sent to the emulator
  /// loopback — an address that means nothing there. Every real build passes
  /// `--dart-define=API_BASE_URL`, so this only decides where a developer's
  /// first `flutter run` points.
  static String get apiBaseUrl {
    if (_apiOverride.isNotEmpty) return _apiOverride;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000/api/v1';
    }
    return 'http://127.0.0.1:8000/api/v1';
  }

  /// The **web** OAuth client id from Google Cloud — the audience the backend
  /// checks the ID token against. Empty hides the "Continue with Google"
  /// button rather than showing one that fails on tap.
  ///
  ///   flutter build apk --dart-define=GOOGLE_SERVER_CLIENT_ID=...apps.googleusercontent.com
  static const String googleServerClientId =
      String.fromEnvironment('GOOGLE_SERVER_CLIENT_ID');

  static const Duration connectTimeout = Duration(seconds: 15);
  static const Duration receiveTimeout = Duration(seconds: 60);
  static const Duration aiTimeout = Duration(seconds: 120);

  static const int pageSize = 25;
  static const Duration searchDebounce = Duration(milliseconds: 350);
  static const Duration syncInterval = Duration(minutes: 5);

  static const bool isProduction = bool.fromEnvironment('dart.vm.product');
}
