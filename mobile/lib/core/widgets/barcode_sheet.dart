import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../theme/app_colors.dart';
import '../utils/device.dart';
import 'common.dart';

/// Opens the camera and returns the first barcode it reads, or null if the user
/// backs out.
///
/// Detection is debounced on the code itself: the camera fires the same barcode
/// many times a second while it stays in frame, and without this a single scan
/// would add the same item to a bill repeatedly.
/// On a machine with no camera plugin this says so and returns null, rather
/// than opening a sheet that throws. Handled here rather than at each call
/// site: there are four, and the fifth would be the one that forgot.
Future<String?> scanBarcode(BuildContext context) {
  if (!Device.canScanBarcodes) {
    showError(context, 'Scanning ${Device.unavailableHere.toLowerCase()}');
    return Future.value();
  }

  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.black,
    builder: (_) => const _BarcodeSheet(),
  );
}

class _BarcodeSheet extends StatefulWidget {
  const _BarcodeSheet();

  @override
  State<_BarcodeSheet> createState() => _BarcodeSheetState();
}

class _BarcodeSheetState extends State<_BarcodeSheet> {
  final _controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    formats: const [
      BarcodeFormat.ean13,
      BarcodeFormat.ean8,
      BarcodeFormat.upcA,
      BarcodeFormat.upcE,
      BarcodeFormat.code128,
      BarcodeFormat.code39,
      BarcodeFormat.qrCode,
    ],
  );

  bool _handled = false;
  bool _torchOn = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    final value = capture.barcodes
        .map((barcode) => barcode.rawValue)
        .firstWhere((raw) => raw != null && raw.trim().isNotEmpty, orElse: () => null);
    if (value == null) return;

    _handled = true;
    Navigator.pop(context, value.trim());
  }

  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.sizeOf(context).height * 0.62;

    return SizedBox(
      height: height,
      child: Stack(
        children: [
          MobileScanner(
            controller: _controller,
            onDetect: _onDetect,
            errorBuilder: (context, error) => _CameraProblem(error: error),
          ),

          // Aiming window — a plain rounded frame reads better in bright shop
          // lighting than a dimmed overlay.
          Center(
            child: Container(
              width: 250,
              height: 150,
              decoration: BoxDecoration(
                border: Border.all(color: AppColors.primary, width: 3),
                borderRadius: BorderRadius.circular(16),
              ),
            ),
          ),

          Positioned(
            left: 0,
            right: 0,
            top: 12,
            child: Row(
              children: [
                IconButton(
                  icon: const Icon(Icons.close, color: Colors.white),
                  onPressed: () => Navigator.pop(context),
                ),
                const Expanded(
                  child: Text(
                    'Point at the barcode',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                IconButton(
                  icon: Icon(
                    _torchOn ? Icons.flash_on : Icons.flash_off,
                    color: Colors.white,
                  ),
                  onPressed: () async {
                    await _controller.toggleTorch();
                    if (mounted) setState(() => _torchOn = !_torchOn);
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CameraProblem extends StatelessWidget {
  const _CameraProblem({required this.error});

  final MobileScannerException error;

  @override
  Widget build(BuildContext context) {
    final message = switch (error.errorCode) {
      MobileScannerErrorCode.permissionDenied =>
        'Karobar needs camera permission to scan barcodes. Turn it on in your '
            'phone settings.',
      MobileScannerErrorCode.unsupported =>
        'This device cannot scan barcodes. Type the code instead.',
      _ => 'The camera could not start. Type the code instead.',
    };

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.no_photography_outlined, color: Colors.white54, size: 40),
            const SizedBox(height: 14),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 18),
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Close'),
            ),
          ],
        ),
      ),
    );
  }
}
