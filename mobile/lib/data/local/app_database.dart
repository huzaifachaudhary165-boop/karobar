import 'dart:convert';

import 'package:drift/drift.dart';

// Where the database actually lives depends on what is running it: a file on a
// phone or a desktop, and SQLite compiled to WebAssembly in a browser. Nothing
// below this line knows the difference, and nothing above it drags `dart:io`
// into a web build — which is what stopped the app compiling for the browser
// at all.
import 'connection/unsupported.dart'
    if (dart.library.io) 'connection/native.dart'
    if (dart.library.js_interop) 'connection/web.dart';

part 'app_database.g.dart';

/// A write the device made while it could not reach the server.
///
/// [clientUuid] is what makes a retry safe: the server keys on it, so pushing
/// the same row twice applies it once. [baseRevision] is what makes a retry
/// *correct*: if someone else changed the record in the meantime the server
/// returns a conflict instead of silently overwriting them.
class OutboxEntries extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get clientUuid => text().unique()();
  TextColumn get entity => text()();
  TextColumn get operation => text().withDefault(const Constant('create'))();
  TextColumn get serverId => text().nullable()();
  TextColumn get payload => text()(); // JSON
  IntColumn get baseRevision => integer().withDefault(const Constant(0))();
  DateTimeColumn get createdAt => dateTime()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  TextColumn get lastError => text().nullable()();
  /// Set once the server rejects it for a reason a retry cannot fix, so the
  /// queue stops hammering and the user can be shown what went wrong.
  BoolColumn get isBlocked => boolean().withDefault(const Constant(false))();
}

/// Last good response for a GET, so lists still render with no signal.
class CachedResponses extends Table {
  TextColumn get key => text()();
  TextColumn get businessId => text()();
  TextColumn get body => text()(); // JSON
  DateTimeColumn get fetchedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {key, businessId};
}

@DriftDatabase(tables: [OutboxEntries, CachedResponses])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(openConnection());

  /// Used by tests — everything lives in memory and dies with the instance.
  AppDatabase.memory() : super(memoryConnection());

  @override
  int get schemaVersion => 1;

  // ── outbox ─────────────────────────────────────────────────────
  Future<int> enqueue(OutboxEntriesCompanion entry) =>
      into(outboxEntries).insert(entry, mode: InsertMode.insertOrReplace);

  /// Oldest first — order matters, because a payment can reference an invoice
  /// that is itself still sitting in the queue.
  Future<List<OutboxEntry>> pending({int limit = 200}) =>
      (select(outboxEntries)
            ..where((row) => row.isBlocked.equals(false))
            ..orderBy([(row) => OrderingTerm.asc(row.id)])
            ..limit(limit))
          .get();

  Future<int> pendingCount() async {
    final count = outboxEntries.id.count();
    final row = await (selectOnly(outboxEntries)
          ..addColumns([count])
          ..where(outboxEntries.isBlocked.equals(false)))
        .getSingle();
    return row.read(count) ?? 0;
  }

  Stream<int> watchPendingCount() {
    final count = outboxEntries.id.count();
    return (selectOnly(outboxEntries)
          ..addColumns([count])
          ..where(outboxEntries.isBlocked.equals(false)))
        .watchSingle()
        .map((row) => row.read(count) ?? 0);
  }

  Future<List<OutboxEntry>> blocked() =>
      (select(outboxEntries)..where((row) => row.isBlocked.equals(true))).get();

  Future<void> settle(String clientUuid) =>
      (delete(outboxEntries)..where((row) => row.clientUuid.equals(clientUuid))).go();

  Future<void> markFailed(String clientUuid, String error, {bool blocked = false}) async {
    final existing = await (select(outboxEntries)
          ..where((row) => row.clientUuid.equals(clientUuid)))
        .getSingleOrNull();
    if (existing == null) return;

    await (update(outboxEntries)..where((row) => row.clientUuid.equals(clientUuid)))
        .write(OutboxEntriesCompanion(
      attempts: Value(existing.attempts + 1),
      lastError: Value(error),
      isBlocked: Value(blocked),
    ));
  }

  Future<void> discard(String clientUuid) => settle(clientUuid);

  Future<void> clearOutbox() => delete(outboxEntries).go();

  // ── response cache ─────────────────────────────────────────────
  Future<void> cacheResponse(String key, String businessId, Object? body) =>
      into(cachedResponses).insert(
        CachedResponsesCompanion.insert(
          key: key,
          businessId: businessId,
          body: jsonEncode(body),
          fetchedAt: DateTime.now(),
        ),
        mode: InsertMode.insertOrReplace,
      );

  Future<({Object? body, DateTime fetchedAt})?> cached(
    String key,
    String businessId,
  ) async {
    final row = await (select(cachedResponses)
          ..where((r) => r.key.equals(key) & r.businessId.equals(businessId)))
        .getSingleOrNull();
    if (row == null) return null;
    return (body: jsonDecode(row.body) as Object?, fetchedAt: row.fetchedAt);
  }

  /// Called on sign-out — a shared phone must not leak one shop's data to the
  /// next person who signs in.
  Future<void> wipe() async {
    await delete(outboxEntries).go();
    await delete(cachedResponses).go();
  }
}

