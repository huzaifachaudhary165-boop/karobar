import 'package:google_sign_in/google_sign_in.dart';

import '../config/env.dart';

/// "Continue with Google" — the fastest way onto a phone where typing a
/// password is the slowest part of signing in.
///
/// All this does is get an **ID token** from Google. Every decision about who
/// that person is stays on the server, which verifies the token's signature and
/// audience against Google's own keys. A token minted for another app will not
/// pass, so nothing here can be spoofed by editing the client.
class GoogleAuth {
  GoogleAuth._();

  static bool _initialised = false;

  /// Whether the button should be shown at all.
  ///
  /// Without a configured client id the sign-in sheet opens and then fails with
  /// a confusing platform error — better to not offer it.
  static bool get isConfigured => Env.googleServerClientId.isNotEmpty;

  static Future<void> _ensureInitialised() async {
    if (_initialised) return;
    await GoogleSignIn.instance.initialize(
      // The *web* client id from Google Cloud, even on Android: it is what the
      // ID token is minted for, and what the backend checks the audience
      // against. Passing the Android client id here produces a token the
      // server correctly rejects.
      serverClientId: Env.googleServerClientId,
    );
    _initialised = true;
  }

  /// Runs the sign-in sheet and returns Google's ID token.
  ///
  /// Returns null when the user backs out — that is not an error and should not
  /// raise a red snackbar at them.
  static Future<String?> idToken() async {
    await _ensureInitialised();

    if (!GoogleSignIn.instance.supportsAuthenticate()) {
      throw const GoogleAuthUnavailable(
        'Google sign-in is not available on this device. Use your phone number '
        'or email instead.',
      );
    }

    try {
      final account = await GoogleSignIn.instance.authenticate();
      final token = account.authentication.idToken;
      if (token == null || token.isEmpty) {
        throw const GoogleAuthUnavailable(
          'Google did not return a sign-in token. Please try again.',
        );
      }
      return token;
    } on GoogleSignInException catch (error) {
      if (error.code == GoogleSignInExceptionCode.canceled) return null;
      throw GoogleAuthUnavailable(_message(error));
    }
  }

  /// Clears the Google session too, so the account picker appears next time
  /// rather than silently signing the previous person back in — this matters on
  /// a shared shop phone.
  static Future<void> signOut() async {
    if (!_initialised) return;
    try {
      await GoogleSignIn.instance.signOut();
    } on GoogleSignInException {
      // Already signed out, or the plugin is unavailable. Nothing to recover.
    }
  }

  static String _message(GoogleSignInException error) => switch (error.code) {
        GoogleSignInExceptionCode.canceled => 'Sign-in cancelled.',
        GoogleSignInExceptionCode.interrupted =>
          'Sign-in was interrupted. Please try again.',
        GoogleSignInExceptionCode.clientConfigurationError =>
          'Google sign-in is not set up correctly for this app.',
        GoogleSignInExceptionCode.providerConfigurationError =>
          'Google sign-in is not available right now.',
        _ => 'Google sign-in failed. Please try another way.',
      };
}

class GoogleAuthUnavailable implements Exception {
  const GoogleAuthUnavailable(this.message);
  final String message;

  @override
  String toString() => message;
}
