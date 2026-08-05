import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/utils/mime.dart';

/// Uploads announce what they are, because nothing else does it for them.
///
/// Dio's `MultipartFile.fromBytes` does not infer a content type — its own
/// documentation says it "currently defaults to application/octet-stream" — and
/// the server refuses that as an unsupported file type. So every photo taken
/// with the camera and every document picked from the gallery failed to upload,
/// whatever it actually was, and the scan screen swallowed the error so nothing
/// said why.
///
/// These types must stay in step with `ALLOWED_MIME` in
/// `backend/app/services/storage_service.py`.
void main() {
  group('photos', () {
    test('the formats a camera produces', () {
      expect(mimeTypeFor('bill.jpg'), 'image/jpeg');
      expect(mimeTypeFor('bill.jpeg'), 'image/jpeg');
      expect(mimeTypeFor('shot.png'), 'image/png');
      expect(mimeTypeFor('photo.webp'), 'image/webp');
    });

    test('heic, which is what a modern phone actually saves', () {
      // Miss this and iPhone photos, and many Android ones, cannot be attached.
      expect(mimeTypeFor('IMG_0042.heic'), 'image/heic');
      expect(mimeTypeFor('IMG_0042.HEIC'), 'image/heic');
      expect(mimeTypeFor('scan.heif'), 'image/heic');
    });

    test('case does not matter — pickers return either', () {
      expect(mimeTypeFor('BILL.JPG'), 'image/jpeg');
      expect(mimeTypeFor('Bill.Png'), 'image/png');
    });
  });

  group('documents', () {
    test('the ones a shopkeeper attaches to a bill', () {
      expect(mimeTypeFor('invoice.pdf'), 'application/pdf');
      expect(mimeTypeFor('items.csv'), 'text/csv');
      expect(mimeTypeFor('notes.txt'), 'text/plain');
      expect(mimeTypeFor('stock.xlsx'),
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      expect(mimeTypeFor('stock.xls'), 'application/vnd.ms-excel');
    });
  });

  group('when the name says nothing', () {
    test('no extension falls back rather than guessing wrong', () {
      expect(mimeTypeFor('scan'), 'application/octet-stream');
      expect(mimeTypeFor('IMG_0042'), 'application/octet-stream');
    });

    test('a trailing dot is not an extension', () {
      expect(mimeTypeFor('file.'), 'application/octet-stream');
    });

    test('an unknown extension is left to the server to judge', () {
      expect(mimeTypeFor('archive.zip'), 'application/octet-stream');
    });

    test('a dot in a folder name is not mistaken for one', () {
      expect(mimeTypeFor('my.photos/bill.jpg'), 'image/jpeg');
    });
  });

  group('isUploadableFile', () {
    test('says yes before the round trip, not after', () {
      expect(isUploadableFile('bill.jpg'), isTrue);
      expect(isUploadableFile('invoice.pdf'), isTrue);
    });

    test('and no for something the server will refuse', () {
      expect(isUploadableFile('app.apk'), isFalse);
      expect(isUploadableFile('nameless'), isFalse);
    });
  });

  test('every type offered is one the server accepts', () {
    // Mirrors ALLOWED_MIME exactly. A type here that the backend does not allow
    // is an upload that fails after the file has been read and sent.
    const serverAccepts = {
      'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/heic',
      'application/pdf', 'text/csv', 'text/plain',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    };

    for (final name in [
      'a.jpg', 'a.jpeg', 'a.jfif', 'a.png', 'a.gif', 'a.webp',
      'a.heic', 'a.heif', 'a.pdf', 'a.csv', 'a.txt', 'a.xls', 'a.xlsx',
    ]) {
      expect(serverAccepts, contains(mimeTypeFor(name)),
          reason: '$name would be sent as a type the server refuses');
    }
  });
}
