/// What a file is, worked out from its name.
///
/// Dio's `MultipartFile.fromBytes` does not infer this — its own documentation
/// says the content type "currently defaults to application/octet-stream" — so
/// every upload announced itself as an anonymous binary blob and the server
/// refused it as an unsupported file type. A photo taken with the camera and a
/// document picked from the gallery both failed, silently, whatever they were.
///
/// The list matches `ALLOWED_MIME` in `backend/app/services/storage_service.py`.
/// Anything not listed still gets sent, with the server making the final call —
/// this is here to stop *correct* files being refused, not to enforce policy on
/// the phone.
library;

const _byExtension = <String, String>{
  // Photos. heic matters: it is what an iPhone produces by default, and many
  // Android phones now too.
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'jfif': 'image/jpeg',
  'png': 'image/png',
  'gif': 'image/gif',
  'webp': 'image/webp',
  'heic': 'image/heic',
  'heif': 'image/heic',
  'bmp': 'image/bmp',

  // Documents a shopkeeper actually attaches to a bill.
  'pdf': 'application/pdf',
  'csv': 'text/csv',
  'txt': 'text/plain',
  'json': 'application/json',
  'xls': 'application/vnd.ms-excel',
  'xlsx':
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};

/// The MIME type for [filename], or `application/octet-stream` when unknown.
String mimeTypeFor(String filename) {
  final dot = filename.lastIndexOf('.');
  if (dot < 0 || dot == filename.length - 1) return 'application/octet-stream';

  final extension = filename.substring(dot + 1).toLowerCase();
  return _byExtension[extension] ?? 'application/octet-stream';
}

/// Whether the server will accept a file with this name.
///
/// Used to say so *before* uploading, rather than after a round trip.
bool isUploadableFile(String filename) {
  final mime = mimeTypeFor(filename);
  return mime != 'application/octet-stream';
}
