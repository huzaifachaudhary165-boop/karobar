import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/local/app_database.dart';

void main() {
  late AppDatabase db;

  setUp(() => db = AppDatabase.memory());
  tearDown(() => db.close());

  OutboxEntriesCompanion change(String uuid, {String entity = 'party'}) =>
      OutboxEntriesCompanion.insert(
        clientUuid: uuid,
        entity: entity,
        payload: jsonEncode({'name': 'Ali Traders'}),
        createdAt: DateTime(2026, 1, 1),
      );

  group('offline outbox', () {
    test('queues a change and counts it as pending', () async {
      await db.enqueue(change('uuid-1'));

      expect(await db.pendingCount(), 1);
      expect((await db.pending()).single.entity, 'party');
    });

    test('re-queuing the same client_uuid replaces rather than duplicates',
        () async {
      await db.enqueue(change('uuid-1'));
      await db.enqueue(change('uuid-1'));

      expect(await db.pendingCount(), 1);
    });

    test('drains oldest first, because a payment can depend on its invoice',
        () async {
      await db.enqueue(change('uuid-1', entity: 'voucher'));
      await db.enqueue(change('uuid-2', entity: 'payment'));

      final queued = await db.pending();
      expect(queued.map((e) => e.entity), ['voucher', 'payment']);
    });

    test('settling a change removes it from the queue', () async {
      await db.enqueue(change('uuid-1'));
      await db.settle('uuid-1');

      expect(await db.pendingCount(), 0);
    });

    test('a blocked change stops being retried but is still visible', () async {
      await db.enqueue(change('uuid-1'));
      await db.markFailed('uuid-1', 'Name is required.', blocked: true);

      expect(await db.pendingCount(), 0);
      final parked = await db.blocked();
      expect(parked.single.lastError, 'Name is required.');
      expect(parked.single.attempts, 1);
    });

    test('a retryable failure counts the attempt and stays in the queue',
        () async {
      await db.enqueue(change('uuid-1'));
      await db.markFailed('uuid-1', 'Server was busy.');
      await db.markFailed('uuid-1', 'Server was busy.');

      expect(await db.pendingCount(), 1);
      expect((await db.pending()).single.attempts, 2);
    });
  });

  group('response cache', () {
    test('serves back what was stored, scoped to the business', () async {
      await db.cacheResponse('/parties', 'biz-1', {
        'items': [
          {'name': 'Ali Traders'}
        ]
      });

      final hit = await db.cached('/parties', 'biz-1');
      expect((hit!.body as Map)['items'], hasLength(1));

      // The same path under a different shop must not leak.
      expect(await db.cached('/parties', 'biz-2'), isNull);
    });

    test('a newer response overwrites the older one', () async {
      await db.cacheResponse('/parties', 'biz-1', {'total': 1});
      await db.cacheResponse('/parties', 'biz-1', {'total': 2});

      final hit = await db.cached('/parties', 'biz-1');
      expect((hit!.body as Map)['total'], 2);
    });
  });

  test('wipe clears both the queue and the cache on sign-out', () async {
    await db.enqueue(change('uuid-1'));
    await db.cacheResponse('/parties', 'biz-1', {'total': 1});

    await db.wipe();

    expect(await db.pendingCount(), 0);
    expect(await db.cached('/parties', 'biz-1'), isNull);
  });

  test('markFailed on an unknown uuid is a no-op, not a crash', () async {
    await db.markFailed('never-queued', 'boom');
    expect(await db.pendingCount(), 0);
  });

  test('Value is exported so callers can set optional columns', () async {
    await db.enqueue(
      OutboxEntriesCompanion.insert(
        clientUuid: 'uuid-9',
        entity: 'item',
        payload: '{}',
        createdAt: DateTime(2026, 1, 1),
        operation: const Value('update'),
        serverId: const Value('server-9'),
        baseRevision: const Value(3),
      ),
    );

    final entry = (await db.pending()).single;
    expect(entry.operation, 'update');
    expect(entry.serverId, 'server-9');
    expect(entry.baseRevision, 3);
  });
}
