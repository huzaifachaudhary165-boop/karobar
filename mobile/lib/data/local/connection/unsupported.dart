import 'package:drift/drift.dart';

/// Picked only if a platform turns up with neither `dart:io` nor a browser.
///
/// Nothing reaches this today. It exists so the conditional import in
/// [AppDatabase] has a default, and so a new platform fails with a sentence
/// that says what is missing rather than a compile error in generated code.
QueryExecutor openConnection() =>
    throw UnsupportedError('Karobar has no local database on this platform.');

QueryExecutor memoryConnection() =>
    throw UnsupportedError('Karobar has no local database on this platform.');
