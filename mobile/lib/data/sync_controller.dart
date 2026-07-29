import 'dart:async';
import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:drift/drift.dart' show Value;
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../core/network/api_exception.dart';
import '../core/storage/token_store.dart';
import 'local/app_database.dart';
import 'repositories.dart';

/// A rejection the server will not accept no matter how many times we retry.
/// Anything else (timeouts, 5xx, no signal) is worth another attempt.
const _terminalReasons = {'validation', 'permission', 'not_found'};

/// How many times a single change is pushed before it is parked for the user
/// to look at, so a poisoned row can't block the whole queue forever.
const _maxAttempts = 5;

@immutable
class SyncState {
  const SyncState({
    this.online = true,
    this.pending = 0,
    this.syncing = false,
    this.lastSyncedAt,
    this.lastError,
    this.conflicts = const [],
  });

  final bool online;
  final int pending;
  final bool syncing;
  final DateTime? lastSyncedAt;
  final String? lastError;
  final List<SyncConflict> conflicts;

  bool get hasPending => pending > 0;

  /// The only state worth interrupting the user for: work is saved on the
  /// phone but the server has not accepted it.
  bool get needsAttention => conflicts.isNotEmpty;

  SyncState copyWith({
    bool? online,
    int? pending,
    bool? syncing,
    DateTime? lastSyncedAt,
    String? lastError,
    bool clearError = false,
    List<SyncConflict>? conflicts,
  }) =>
      SyncState(
        online: online ?? this.online,
        pending: pending ?? this.pending,
        syncing: syncing ?? this.syncing,
        lastSyncedAt: lastSyncedAt ?? this.lastSyncedAt,
        lastError: clearError ? null : (lastError ?? this.lastError),
        conflicts: conflicts ?? this.conflicts,
      );
}

@immutable
class SyncConflict {
  const SyncConflict({
    required this.entity,
    required this.clientUuid,
    required this.reason,
    required this.message,
  });

  final String entity;
  final String clientUuid;
  final String reason;
  final String message;

  factory SyncConflict.fromJson(Map<String, dynamic> json) => SyncConflict(
        entity: json['entity']?.toString() ?? '',
        clientUuid: json['client_uuid']?.toString() ?? '',
        reason: json['reason']?.toString() ?? 'unknown',
        message: json['message']?.toString() ?? 'The server rejected this change.',
      );
}

/// Owns the offline queue.
///
/// Screens never talk to it directly for reads — [ApiClient] already falls back
/// to cached responses. They talk to it for *writes* that failed because the
/// phone had no signal: [enqueue] parks the change, and it is pushed the moment
/// connectivity returns.
class SyncController extends ChangeNotifier {
  SyncController({
    required AppDatabase db,
    required SyncRepository repository,
    required TokenStore store,
  })  : _db = db,
        _repository = repository,
        _store = store {
    _watchConnectivity();
    _watchQueue();
  }

  final AppDatabase _db;
  final SyncRepository _repository;
  final TokenStore _store;
  static const _uuid = Uuid();

  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  StreamSubscription<int>? _queueSub;
  Timer? _retryTimer;

  SyncState _state = const SyncState();
  SyncState get state => _state;

  void _set(SyncState next) {
    _state = next;
    notifyListeners();
  }

  void _watchConnectivity() {
    // A first reading, then every change. `none` is the only result that means
    // truly offline — VPN, ethernet and the rest all count as a path out.
    unawaited(Connectivity().checkConnectivity().then(_onConnectivity));
    _connectivitySub = Connectivity().onConnectivityChanged.listen(_onConnectivity);
  }

  void _onConnectivity(List<ConnectivityResult> results) {
    final online = results.any((r) => r != ConnectivityResult.none);
    if (online == _state.online) return;

    _set(_state.copyWith(online: online, clearError: online));
    // Coming back online is the natural moment to flush.
    if (online && _state.hasPending) unawaited(syncNow());
  }

  void _watchQueue() {
    _queueSub = _db.watchPendingCount().listen((count) {
      if (count != _state.pending) _set(_state.copyWith(pending: count));
    });
  }

  /// Parks a write that could not reach the server.
  ///
  /// [entity] must be one of the names the backend's `SyncChange.entity` accepts
  /// (`party`, `item`, `voucher`, `payment`, `expense`, …).
  Future<void> enqueue({
    required String entity,
    required Map<String, dynamic> data,
    String operation = 'create',
    String? serverId,
    int baseRevision = 0,
    String? clientUuid,
  }) async {
    await _db.enqueue(
      OutboxEntriesCompanion.insert(
        clientUuid: clientUuid ?? _uuid.v4(),
        entity: entity,
        payload: jsonEncode(data),
        createdAt: DateTime.now(),
        operation: Value(operation),
        serverId: Value(serverId),
        baseRevision: Value(baseRevision),
      ),
    );
    if (_state.online) unawaited(syncNow());
  }

  /// Pushes everything queued. Safe to call at any time — it no-ops while a
  /// push is already in flight, and every change carries a `client_uuid` so a
  /// duplicate push applies once.
  Future<void> syncNow() async {
    if (_state.syncing) return;
    if (!_state.online) {
      _set(_state.copyWith(lastError: 'Waiting for a connection.'));
      return;
    }

    final queued = await _db.pending();
    if (queued.isEmpty) {
      _set(_state.copyWith(lastSyncedAt: DateTime.now(), clearError: true, conflicts: const []));
      return;
    }

    _set(_state.copyWith(syncing: true, clearError: true));

    try {
      final response = await _repository.push(
        deviceId: await _store.deviceId(),
        changes: [
          for (final entry in queued)
            {
              'entity': entry.entity,
              'operation': entry.operation,
              'client_uuid': entry.clientUuid,
              if (entry.serverId != null) 'server_id': entry.serverId,
              'data': jsonDecode(entry.payload),
              'base_revision': entry.baseRevision,
              'client_updated_at': entry.createdAt.toUtc().toIso8601String(),
            },
        ],
      );

      for (final applied in (response['applied'] as List? ?? const [])) {
        await _db.settle((applied as Map)['client_uuid'].toString());
      }

      final conflicts = [
        for (final raw in (response['conflicts'] as List? ?? const []))
          SyncConflict.fromJson(Map<String, dynamic>.from(raw as Map)),
      ];

      for (final conflict in conflicts) {
        await _db.markFailed(
          conflict.clientUuid,
          conflict.message,
          // A stale revision can be resolved by re-reading and re-sending;
          // a validation or permission failure never will be.
          blocked: _terminalReasons.contains(conflict.reason),
        );
      }

      // Anything that ran out of attempts gets parked too.
      for (final entry in queued) {
        if (entry.attempts + 1 >= _maxAttempts) {
          await _db.markFailed(entry.clientUuid, entry.lastError ?? 'Gave up after retries.',
              blocked: true);
        }
      }

      _set(_state.copyWith(
        syncing: false,
        lastSyncedAt: DateTime.now(),
        conflicts: conflicts,
        clearError: true,
      ));
    } on ApiException catch (error) {
      _set(_state.copyWith(
        syncing: false,
        online: !error.isOffline,
        lastError: error.message,
      ));
      if (!error.isOffline) _scheduleRetry();
    } catch (error) {
      _set(_state.copyWith(syncing: false, lastError: error.toString()));
      _scheduleRetry();
    }
  }

  /// One delayed retry after a server-side failure. Connectivity changes drive
  /// the rest, so this only covers "the server was briefly unhappy".
  void _scheduleRetry() {
    _retryTimer?.cancel();
    _retryTimer = Timer(const Duration(seconds: 30), () {
      if (_state.online && _state.hasPending) unawaited(syncNow());
    });
  }

  /// Throws away a change the user has decided not to keep.
  Future<void> discard(String clientUuid) async {
    await _db.discard(clientUuid);
    _set(_state.copyWith(
      conflicts: _state.conflicts.where((c) => c.clientUuid != clientUuid).toList(),
    ));
  }

  /// Anything the server refused for good, so the UI can show it.
  Future<List<OutboxEntry>> blockedEntries() => _db.blocked();

  /// Called on sign-out. Queued writes belong to the session that made them.
  Future<void> reset() async {
    await _db.wipe();
    _set(const SyncState());
  }

  @override
  void dispose() {
    _connectivitySub?.cancel();
    _queueSub?.cancel();
    _retryTimer?.cancel();
    super.dispose();
  }
}
