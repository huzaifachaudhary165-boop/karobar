import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqlite3/sqlite3.dart';
import 'package:sqlite3_flutter_libs/sqlite3_flutter_libs.dart';

/// The phone and the desktop: a real file under the app's own directory.
QueryExecutor openConnection() {
  return LazyDatabase(() async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(dir.path, 'karobar.sqlite'));

    // Android ships old SQLite builds; this pulls in a modern bundled one and
    // works around a known tmpdir bug.
    await applyWorkaroundToOpenSqlite3OnOldAndroidVersions();
    sqlite3.tempDirectory = (await getTemporaryDirectory()).path;

    return NativeDatabase.createInBackground(file);
  });
}

/// Used by tests — everything lives in memory and dies with the instance.
QueryExecutor memoryConnection() => NativeDatabase.memory();
