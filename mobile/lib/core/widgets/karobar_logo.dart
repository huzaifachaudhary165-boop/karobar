import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// The Karobar mark: an open ledger with a rising bar chart, drawn rather than
/// shipped as an asset so it stays crisp at every size and can recolour itself.
class KarobarMark extends StatelessWidget {
  const KarobarMark({super.key, this.size = 48, this.inverted = false});

  final double size;

  /// White mark on a transparent background, for use on the orange splash.
  final bool inverted;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        gradient: inverted
            ? null
            : const LinearGradient(
                colors: [AppColors.primary, AppColors.primaryDarker],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
        color: inverted ? Colors.transparent : null,
        borderRadius: BorderRadius.circular(size * 0.28),
        boxShadow: inverted
            ? null
            : [
                BoxShadow(
                  color: AppColors.primary.withValues(alpha: 0.30),
                  blurRadius: size * 0.28,
                  offset: Offset(0, size * 0.10),
                ),
              ],
      ),
      child: CustomPaint(
        painter: _MarkPainter(
          color: inverted ? AppColors.white : AppColors.white,
        ),
      ),
    );
  }
}

/// Draws the mark: a bill with a torn bottom edge and three rising bars punched
/// out of it.
///
/// The geometry below is the same 100×100 space used by
/// `scripts/generate_icons.py`, so the in-app mark and the launcher icon are the
/// same drawing — change one and regenerate the other.
class _MarkPainter extends CustomPainter {
  const _MarkPainter({required this.color});

  final Color color;

  static const _billLeft = 24.0;
  static const _billRight = 76.0;
  static const _billTop = 14.0;
  static const _billBottom = 72.0;
  static const _teeth = 4;
  static const _toothDepth = 7.0;
  static const _corner = 6.0;

  static const _bars = [(x: 36.0, top: 48.0), (x: 50.0, top: 37.0), (x: 64.0, top: 26.0)];
  static const _barWidth = 8.0;
  static const _barBottom = 62.0;

  @override
  void paint(Canvas canvas, Size size) {
    // The mark is inset so it never touches the tile's rounded corners.
    const artboard = 100.0;
    final scale = size.width / artboard * 0.78;
    final offset = (size.width - artboard * scale) / 2;

    canvas.save();
    canvas.translate(offset, offset);
    canvas.scale(scale);

    final bill = Path()
      ..moveTo(_billLeft, _billTop + _corner)
      ..arcToPoint(
        const Offset(_billLeft + _corner, _billTop),
        radius: const Radius.circular(_corner),
      )
      ..lineTo(_billRight - _corner, _billTop)
      ..arcToPoint(
        const Offset(_billRight, _billTop + _corner),
        radius: const Radius.circular(_corner),
      )
      ..lineTo(_billRight, _billBottom - _toothDepth);

    // Torn edge: zigzag from the right back to the left.
    const toothWidth = (_billRight - _billLeft) / _teeth;
    for (var index = 0; index < _teeth; index++) {
      bill
        ..lineTo(_billRight - (index + 0.5) * toothWidth, _billBottom)
        ..lineTo(_billRight - (index + 1) * toothWidth, _billBottom - _toothDepth);
    }
    bill.close();

    // Bars are subtracted, so the tile's gradient shows through them.
    var bars = Path();
    for (final bar in _bars) {
      bars = Path.combine(
        PathOperation.union,
        bars,
        Path()
          ..addRRect(
            RRect.fromRectAndRadius(
              Rect.fromLTRB(bar.x - _barWidth / 2, bar.top, bar.x + _barWidth / 2, _barBottom),
              const Radius.circular(_barWidth / 2),
            ),
          ),
      );
    }

    canvas.drawPath(
      Path.combine(PathOperation.difference, bill, bars),
      Paint()..color = color,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_MarkPainter oldDelegate) => oldDelegate.color != color;
}

/// Full lock-up: mark + the Urdu wordmark **کاروبار** with a Latin subtitle.
class KarobarLogo extends StatelessWidget {
  const KarobarLogo({
    super.key,
    this.size = LogoSize.medium,
    this.direction = Axis.horizontal,
    this.onDark = false,
    this.showSubtitle = true,
  });

  final LogoSize size;
  final Axis direction;
  final bool onDark;
  final bool showSubtitle;

  @override
  Widget build(BuildContext context) {
    final metrics = size.metrics;
    final wordColor = onDark ? AppColors.white : AppColors.textPrimary;
    // Was 0.75, which on the old pale backdrop left "KAROBAR" barely present.
    final subtitleColor =
        onDark ? AppColors.white.withValues(alpha: 0.92) : AppColors.textMuted;

    final wordmark = Column(
      crossAxisAlignment:
          direction == Axis.vertical ? CrossAxisAlignment.center : CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        // Urdu is right-to-left; forcing the directionality keeps the glyphs joined
        // correctly even when the app locale is English.
        Directionality(
          textDirection: TextDirection.rtl,
          child: Text(
            'کاروبار',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: metrics.urdu,
              height: 1.6,
              // Heavier on a coloured backdrop: Urdu strokes are fine and thin,
              // and they are the first thing to disappear against orange.
              fontWeight: onDark ? FontWeight.w800 : FontWeight.w700,
              color: wordColor,
              letterSpacing: 0,
              shadows: onDark
                  ? [
                      Shadow(
                        color: Colors.black.withValues(alpha: 0.22),
                        blurRadius: metrics.urdu * 0.14,
                        offset: Offset(0, metrics.urdu * 0.035),
                      ),
                    ]
                  : null,
            ),
          ),
        ),
        if (showSubtitle) ...[
          SizedBox(height: metrics.gap * 0.15),
          Text(
            'KAROBAR',
            style: TextStyle(
              fontSize: metrics.latin,
              fontWeight: FontWeight.w800,
              letterSpacing: metrics.latin * 0.34,
              color: subtitleColor,
            ),
          ),
        ],
      ],
    );

    final mark = KarobarMark(size: metrics.mark, inverted: onDark);

    if (direction == Axis.vertical) {
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [mark, SizedBox(height: metrics.gap), wordmark],
      );
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [mark, SizedBox(width: metrics.gap), wordmark],
    );
  }
}

enum LogoSize {
  small,
  medium,
  large,
  hero;

  ({double mark, double urdu, double latin, double gap}) get metrics => switch (this) {
        LogoSize.small => (mark: 28, urdu: 17, latin: 8, gap: 8),
        LogoSize.medium => (mark: 44, urdu: 26, latin: 10, gap: 12),
        LogoSize.large => (mark: 68, urdu: 38, latin: 13, gap: 16),
        LogoSize.hero => (mark: 104, urdu: 56, latin: 17, gap: 22),
      };
}

/// Decorative background used behind the splash and auth screens.
///
/// This was a flat `AppColors.primary`. White on that orange measures about
/// 2.8:1 — under every legibility threshold there is — and the wordmark read as
/// washed out, especially outdoors where these phones are actually used.
///
/// The fix is the backdrop rather than the text: a darker wordmark on orange is
/// *worse* (deep orange on orange is roughly 1.85:1). Deepening the background
/// takes white to about 5.2:1 at the bottom and 3.6:1 at the top, so the logo
/// reads as solid and deliberate instead of faint.
class BrandBackdrop extends StatelessWidget {
  const BrandBackdrop({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        const Positioned.fill(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [AppColors.primaryDark, AppColors.primaryDarker],
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
              ),
            ),
          ),
        ),
        Positioned(
          top: -90,
          right: -70,
          child: _Blob(size: 260, color: AppColors.white.withValues(alpha: 0.10)),
        ),
        Positioned(
          bottom: -120,
          left: -80,
          child: _Blob(size: 320, color: AppColors.white.withValues(alpha: 0.07)),
        ),
        child,
      ],
    );
  }
}

class _Blob extends StatelessWidget {
  const _Blob({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Transform.rotate(
      angle: math.pi / 7,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(size * 0.38),
        ),
      ),
    );
  }
}
