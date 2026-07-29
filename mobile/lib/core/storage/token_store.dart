import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Tokens live in the OS keystore; everything else in shared preferences.
class TokenStore {
  TokenStore(this._prefs);

  static const _secure = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  static const _kAccess = 'karobar.access_token';
  static const _kRefresh = 'karobar.refresh_token';
  static const _kBusiness = 'karobar.business_id';
  static const _kDevice = 'karobar.device_id';
  static const _kUser = 'karobar.user';
  static const _kBusinesses = 'karobar.businesses';
  static const _kPermissions = 'karobar.permissions';
  static const _kSyncSeq = 'karobar.sync_seq';
  static const _kLanguage = 'karobar.language';
  static const _kThemeMode = 'karobar.theme_mode';
  static const _kOnboarded = 'karobar.onboarded';
  static const _kPrinter = 'karobar.printer_address';
  static const _kPrinter80 = 'karobar.printer_80mm';

  final SharedPreferences _prefs;

  // Reading a key out of the OS keystore is a platform-channel round trip plus
  // a decrypt. Every outgoing request needs the access token, so paying that
  // cost per request put tens of milliseconds in front of *every* screen —
  // felt as the app being uniformly sluggish rather than as one slow feature.
  //
  // The token is held in memory after the first read. It is already in this
  // process's memory the moment it is used as a header, so keeping it there
  // gives an attacker who can read our heap nothing they did not already have;
  // the keystore is what protects it at rest, and it still does.
  String? _accessCache;
  String? _refreshCache;
  bool _accessLoaded = false;
  bool _refreshLoaded = false;

  static Future<TokenStore> create() async =>
      TokenStore(await SharedPreferences.getInstance());

  // ── tokens ─────────────────────────────────────────────────────
  Future<String?> get accessToken async {
    if (_accessLoaded) return _accessCache;
    _accessCache = await _secure.read(key: _kAccess);
    _accessLoaded = true;
    return _accessCache;
  }

  Future<String?> get refreshToken async {
    if (_refreshLoaded) return _refreshCache;
    _refreshCache = await _secure.read(key: _kRefresh);
    _refreshLoaded = true;
    return _refreshCache;
  }

  Future<void> saveTokens({required String access, required String refresh}) async {
    // Memory first: a refresh that lands mid-flight must not let another
    // request read the old token back out of the cache while the write is
    // still in progress.
    _accessCache = access;
    _refreshCache = refresh;
    _accessLoaded = _refreshLoaded = true;

    await _secure.write(key: _kAccess, value: access);
    await _secure.write(key: _kRefresh, value: refresh);
  }

  Future<void> clearTokens() async {
    _accessCache = _refreshCache = null;
    _accessLoaded = _refreshLoaded = true;

    await _secure.delete(key: _kAccess);
    await _secure.delete(key: _kRefresh);
  }

  // ── session ────────────────────────────────────────────────────
  String? get businessId => _prefs.getString(_kBusiness);
  Future<void> setBusinessId(String? id) async =>
      id == null ? _prefs.remove(_kBusiness) : _prefs.setString(_kBusiness, id);

  Map<String, dynamic>? get user => _decode(_prefs.getString(_kUser));
  Future<void> setUser(Map<String, dynamic>? value) async => value == null
      ? _prefs.remove(_kUser)
      : _prefs.setString(_kUser, jsonEncode(value));

  List<Map<String, dynamic>> get businesses {
    final raw = _prefs.getString(_kBusinesses);
    if (raw == null) return const [];
    final decoded = jsonDecode(raw);
    return decoded is List
        ? decoded.map((e) => Map<String, dynamic>.from(e as Map)).toList()
        : const [];
  }

  Future<void> setBusinesses(List<Map<String, dynamic>> value) async =>
      _prefs.setString(_kBusinesses, jsonEncode(value));

  Set<String> get permissions => _prefs.getStringList(_kPermissions)?.toSet() ?? const {};
  Future<void> setPermissions(List<String> value) async =>
      _prefs.setStringList(_kPermissions, value);

  bool can(String permission) => permissions.isEmpty || permissions.contains(permission);

  /// A stable per-install id — the sync engine keys every cursor on it.
  ///
  /// Held in memory because it is read on every outgoing request and, once
  /// generated, never changes for the life of the install.
  String? _deviceIdCache;

  Future<String> deviceId() async {
    if (_deviceIdCache != null) return _deviceIdCache!;

    final existing = _prefs.getString(_kDevice);
    if (existing != null) return _deviceIdCache = existing;

    final generated = 'dev_${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}';
    await _prefs.setString(_kDevice, generated);
    return _deviceIdCache = generated;
  }

  int get syncSeq => _prefs.getInt(_kSyncSeq) ?? 0;
  Future<void> setSyncSeq(int value) async => _prefs.setInt(_kSyncSeq, value);

  // ── preferences ────────────────────────────────────────────────
  String get language => _prefs.getString(_kLanguage) ?? 'en';
  Future<void> setLanguage(String value) async => _prefs.setString(_kLanguage, value);

  String get themeMode => _prefs.getString(_kThemeMode) ?? 'system';
  Future<void> setThemeMode(String value) async => _prefs.setString(_kThemeMode, value);

  bool get onboarded => _prefs.getBool(_kOnboarded) ?? false;
  Future<void> setOnboarded(bool value) async => _prefs.setBool(_kOnboarded, value);

  /// The last thermal printer used, so the second bill onwards is one tap.
  /// Deliberately survives sign-out — the printer belongs to the shop counter,
  /// not to whoever is logged in.
  String? get printerAddress => _prefs.getString(_kPrinter);
  bool get printerIs80mm => _prefs.getBool(_kPrinter80) ?? false;

  Future<void> setPrinter({required String address, required bool is80mm}) async {
    await _prefs.setString(_kPrinter, address);
    await _prefs.setBool(_kPrinter80, is80mm);
  }

  Future<void> signOut() async {
    await clearTokens();
    await _prefs.remove(_kUser);
    await _prefs.remove(_kBusiness);
    await _prefs.remove(_kBusinesses);
    await _prefs.remove(_kPermissions);
    await _prefs.remove(_kSyncSeq);
  }

  Map<String, dynamic>? _decode(String? raw) =>
      raw == null ? null : Map<String, dynamic>.from(jsonDecode(raw) as Map);
}
