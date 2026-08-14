import 'dart:convert';

import 'package:share_plus/share_plus.dart';

/// Shares a generated document without ever putting it on disk.
///
/// The label sheet, the invoice preview and the tax export are all built in
/// memory and handed straight to the share sheet — which is where the printer,
/// the PDF writer and WhatsApp already live.
///
/// Written from bytes rather than a temp file because a browser has no
/// temporary directory: `getTemporaryDirectory()` throws there, and these three
/// screens are otherwise perfectly usable on a shop's computer. It is the
/// better path on a phone too — nothing is left behind to clean up, and one
/// fewer thing can fail between building the document and sharing it.
Future<void> shareDocument(
  String content, {
  required String filename,
  required String mimeType,
  String? subject,
}) {
  return Share.shareXFiles(
    [
      XFile.fromData(
        utf8.encode(content),
        mimeType: mimeType,
        name: filename,
      ),
    ],
    // Without this the share sheet offers the document under a generated name.
    // A shopkeeper looking for it later in their downloads needs it to say
    // what it is.
    fileNameOverrides: [filename],
    subject: subject,
  );
}
