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

/// Sends a write, and parks it in the offline queue if the phone has no signal.
///
/// Only genuine transport failures are queued. A 422 or a 403 means the server
/// saw the request and said no, so retrying it later would fail the same way —
/// those still throw and the form shows the error.
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
    if (!error.isOffline) rethrow;

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
const queuedMessage = 'Saved on this phone. It will upload when you are back online.';
