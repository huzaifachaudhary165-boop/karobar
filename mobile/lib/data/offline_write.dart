import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../providers.dart';

/// The outcome of a save that may have gone to the queue instead of the server.
class SaveResult<T> {
  const SaveResult.saved(this.value)
      : queued = false,
        clientUuid = null;
  const SaveResult.queued(this.clientUuid)
      : queued = true,
        value = null;

  /// The server's response — null when the change is still sitting in the outbox.
  final T? value;
  final bool queued;
  final String? clientUuid;
}

/// Sends a write, and parks it in the offline queue when the server could not
/// take it.
///
/// A 422 or a 403 means the server saw the request and said no, so retrying it
/// later would fail the same way — those still throw and the form shows the
/// error.
///
/// A 5xx is the opposite: the server did not say no, it fell over. Measured
/// against the live deployment, three writes in six came back
/// `database_error` inside one minute and every one of them succeeded on a
/// retry a moment later. Rethrowing those threw away a bill the shopkeeper had
/// just keyed in, for a reason that had nothing to do with them and would be
/// gone by the time they finished typing it again.
///
/// Queueing is safe even if the write did land before the server fell over:
/// every queued row carries a `client_uuid` and the server keys on it, so the
/// same bill pushed twice is applied once.
///
/// [entity] must be a name the backend's `SyncChange.entity` accepts:
/// `party`, `item`, `voucher`, `payment`, `expense`, `expense_category`,
/// `party_group`, `item_category`, `unit`, `godown`, `item_batch`, `tax_rate`,
/// `account`.
Future<SaveResult<T>> saveOrQueue<T>(
  WidgetRef ref, {
  required String entity,
  required Map<String, dynamic> data,
  required Future<T> Function() send,
  String operation = 'create',
  String? serverId,
  int baseRevision = 0,
}) async {
  try {
    return SaveResult<T>.saved(await send());
  } on ApiException catch (error) {
    if (!error.isOffline && !error.isServerFault) rethrow;

    final controller = ref.read(syncControllerProvider);
    final clientUuid = data['client_uuid']?.toString();
    await controller.enqueue(
      entity: entity,
      data: data,
      operation: operation,
      serverId: serverId,
      baseRevision: baseRevision,
      clientUuid: clientUuid,
    );
    return SaveResult<T>.queued(clientUuid);
  }
}

/// What to tell the user after [saveOrQueue] took the offline path.
/// Deliberately does not say "when you are back online".
///
/// This path is now also taken when the signal is fine and the server fell
/// over, and telling somebody with four bars to wait for a connection is worse
/// than saying nothing — they go looking for a problem that is not on their
/// side of it.
const queuedMessage = 'Saved on this phone. It will upload by itself.';
