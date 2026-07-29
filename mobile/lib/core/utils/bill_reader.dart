import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';

/// Reads the text off a photographed bill, on the device.
///
/// This is the half of scanning that used to need a paid vision model. Google
/// ML Kit ships the recognition model with the app, so it costs nothing, has no
/// quota, and works with no signal — the photo never leaves the phone unless
/// the shopkeeper separately chooses to keep it. Only the extracted text is
/// sent up, where the assistant turns it into a purchase bill.
class BillReader {
  BillReader._();

  /// Created on first use and recreated after [dispose], so reopening the scan
  /// screen doesn't hand back a closed native recogniser.
  static TextRecognizer? _instance;

  static TextRecognizer get _recognizer =>
      _instance ??= TextRecognizer(script: TextRecognitionScript.latin);

  /// Extracts text from an image file, laid out so a bill still reads as a bill.
  ///
  /// ML Kit returns blocks in no particular order, and a naive join scrambles
  /// an itemised table into nonsense. Sorting by vertical position first, then
  /// horizontal, keeps rows together and columns in reading order — which is
  /// what lets the model line a quantity up with its rate.
  static Future<BillText> read(String imagePath) async {
    final recognised = await _recognizer.processImage(InputImage.fromFilePath(imagePath));

    final lines = <TextLine>[];
    for (final block in recognised.blocks) {
      lines.addAll(block.lines);
    }

    lines.sort((a, b) {
      // Treat lines within ~12px vertically as the same row of a table.
      final dy = a.boundingBox.center.dy - b.boundingBox.center.dy;
      if (dy.abs() > 12) return dy.compareTo(0);
      return a.boundingBox.left.compareTo(b.boundingBox.left);
    });

    final buffer = StringBuffer();
    double? previousY;
    for (final line in lines) {
      final y = line.boundingBox.center.dy;
      if (previousY != null && (y - previousY).abs() <= 12) {
        buffer.write('  ');           // same row — keep the columns side by side
      } else if (previousY != null) {
        buffer.writeln();
      }
      buffer.write(line.text.trim());
      previousY = y;
    }

    final text = buffer.toString().trim();
    return BillText(
      text: text,
      lineCount: lines.length,
      // ML Kit reports confidence per element and often leaves it null, so the
      // honest signal here is how much text came back at all.
      isUsable: text.length >= 12 && lines.length >= 2,
    );
  }

  /// Frees the native recogniser and the model it holds in memory. Safe to call
  /// more than once; the next [read] simply creates a fresh one.
  static Future<void> dispose() async {
    final open = _instance;
    _instance = null;
    await open?.close();
  }
}

class BillText {
  const BillText({
    required this.text,
    required this.lineCount,
    required this.isUsable,
  });

  final String text;
  final int lineCount;
  final bool isUsable;

  /// What to tell someone whose photo came back empty. Almost always a
  /// lighting or framing problem, so the advice is about the photo.
  String get problem => lineCount == 0
      ? 'No text could be read from that photo. Try again in better light, '
          'holding the bill flat so it fills the frame.'
      : 'Only a little text could be read. Move closer, avoid shadows across '
          'the bill, and keep the camera steady.';
}
