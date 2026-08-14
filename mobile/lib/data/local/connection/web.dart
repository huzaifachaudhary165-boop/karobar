import 'package:drift/drift.dart';
import 'package:drift/wasm.dart';
import 'package:flutter/foundation.dart';

/// The browser: SQLite compiled to WebAssembly, stored by the browser itself.
///
/// The two files this needs — `sqlite3.wasm` and `drift_worker.js` — are served
/// from the site root alongside the app, so the URLs are relative and the same
/// build works on any domain the shop is given.
///
/// drift picks the best storage the browser offers, in this order: OPFS (a real
/// filesystem, survives everything), then IndexedDB, then memory. The last one
/// means a refresh loses what is in it, which for Karobar is the outbox and the
/// response cache — the shop's own records are on the server and are never at
/// risk. Rather than refuse to start on an old browser, it starts and says so
/// in the console, because a shopkeeper with a signal loses nothing either way.
QueryExecutor openConnection() {
  return LazyDatabase(() async {
    final result = await WasmDatabase.open(
      databaseName: 'karobar',
      sqlite3Uri: Uri.parse('sqlite3.wasm'),
      driftWorkerUri: Uri.parse('drift_worker.js'),
    );

    if (result.missingFeatures.isNotEmpty) {
      debugPrint(
        'Karobar: this browser is missing ${result.missingFeatures}. '
        'Offline records may not survive a refresh.',
      );
    }

    return result.resolvedExecutor;
  });
}

/// Tests run on the VM, never here.
QueryExecutor memoryConnection() =>
    throw UnsupportedError('In-memory database is for tests, which do not run '
        'in a browser.');
