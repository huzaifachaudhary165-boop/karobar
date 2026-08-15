import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/strings.dart';
import '../theme/app_colors.dart';
import '../utils/device.dart';
import 'common.dart';

/// Where the phone app comes from.
///
/// Hosted on GitHub Releases rather than served from this site: the file is
/// the better part of a hundred megabytes, and committing it beside the web
/// build would add that much to the repository every time it is rebuilt.
abstract final class PhoneApp {
  static const _base =
      'https://github.com/huzaifachaudhary165-boop/karobar/releases/latest/download';

  /// Every Android phone, at the cost of carrying all three architectures.
  static const universal = '$_base/karobar.apk';

  /// The same app at well under half the size, for phones from about 2017
  /// onwards — which is most of them, but not all, which is why it is the
  /// second choice and not the first.
  static const arm64 = '$_base/karobar-arm64.apk';

  static const universalSize = '112 MB';
  static const arm64Size = '43 MB';

  static Future<void> open(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}

/// An offer to install the phone app, shown only where it is worth making.
///
/// Three things exist on the phone and cannot exist in a browser: scanning a
/// barcode with the camera, reading a supplier's bill from a photo, and
/// printing on a Bluetooth thermal printer. Until now the app said so and
/// stopped there, which leaves a shopkeeper knowing what they are missing and
/// no way to get it.
///
/// Never shown on a phone. Offering someone the app they are already using is
/// how a screen loses their trust.
class GetTheApp extends StatelessWidget {
  const GetTheApp({super.key, this.reason, this.compact = false});

  /// What they were trying to do when this appeared — "Scanning" — so the card
  /// answers the question they actually asked.
  final String? reason;

  /// A single line, for a screen that has already said its piece.
  final bool compact;

  @override
  Widget build(BuildContext context) {
    if (!Device.isWeb) return const SizedBox.shrink();

    final theme = Theme.of(context);

    if (compact) {
      return TextButton.icon(
        onPressed: () => PhoneApp.open(PhoneApp.universal),
        icon: const Icon(Icons.android, size: 18),
        label: Text(context.t('Get the phone app')),
      );
    }

    return AppCard(
      borderColor: AppColors.primary.withValues(alpha: 0.4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: AppColors.primary.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(11),
                ),
                child: const Icon(Icons.android, color: AppColors.primary, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      context.t('Karobar on your phone'),
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      context.t(reason ??
                          'Scan barcodes with the camera, read a supplier bill '
                              'from a photo, and print on a thermal printer.'),
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: () => PhoneApp.open(PhoneApp.universal),
              icon: const Icon(Icons.download_outlined, size: 18),
              label: Text(
                context.t('Download for Android (${PhoneApp.universalSize})'),
              ),
            ),
          ),
          const SizedBox(height: 4),
          // Offered second and described by what decides it — size against
          // certainty — because "arm64-v8a" is not a choice anybody at a
          // counter can make.
          Align(
            alignment: Alignment.center,
            child: TextButton(
              onPressed: () => PhoneApp.open(PhoneApp.arm64),
              child: Text(
                context.t('Smaller download for newer phones '
                    '(${PhoneApp.arm64Size})'),
                style: theme.textTheme.bodySmall,
              ),
            ),
          ),
          Text(
            context.t('Your phone will ask to allow installing from outside '
                'the Play Store. That is normal — allow it once.'),
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.textTheme.bodySmall?.color?.withValues(alpha: 0.7),
            ),
          ),
        ],
      ),
    );
  }
}
