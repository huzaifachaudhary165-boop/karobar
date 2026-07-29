import 'package:flutter/material.dart';

/// The Karobar palette: warm orange on white, with muted support colours that
/// stay legible on a cheap phone screen in daylight.
abstract final class AppColors {
  // Brand
  static const Color primary = Color(0xFFF97316); // orange 500
  static const Color primaryDark = Color(0xFFEA580C); // orange 600
  static const Color primaryDarker = Color(0xFFC2410C); // orange 700
  static const Color primaryLight = Color(0xFFFFEDD5); // orange 100
  static const Color primarySurface = Color(0xFFFFF7ED); // orange 50

  // Neutrals
  static const Color white = Color(0xFFFFFFFF);
  static const Color background = Color(0xFFFAFAF9);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceAlt = Color(0xFFF5F5F4);
  static const Color border = Color(0xFFE7E5E4);
  static const Color divider = Color(0xFFF0EFEE);

  // Text
  static const Color textPrimary = Color(0xFF1C1917);
  static const Color textSecondary = Color(0xFF57534E);
  static const Color textMuted = Color(0xFF8A8580);
  static const Color textOnPrimary = Color(0xFFFFFFFF);

  // Semantic — money in and money out are the two colours users read fastest.
  //
  // The `*Light` and `primaryLight`/`primarySurface` washes below are LIGHT
  // THEME ONLY. They are near-white by design, so on a dark page they render as
  // the brightest thing on screen with near-white text on top — invisible.
  // Reach for `softTint(accent, brightness)` and `onSoftTint(...)` instead;
  // they produce the same effect and adapt. These stay only because the
  // `ColorScheme` needs fixed light-theme container colours.
  static const Color success = Color(0xFF16A34A);
  static const Color successLight = Color(0xFFDCFCE7);
  static const Color danger = Color(0xFFDC2626);
  static const Color dangerLight = Color(0xFFFEE2E2);
  static const Color warning = Color(0xFFD97706);
  static const Color warningLight = Color(0xFFFEF3C7);
  static const Color info = Color(0xFF0284C7);
  static const Color infoLight = Color(0xFFE0F2FE);

  // Dark theme
  static const Color darkBackground = Color(0xFF15130F);
  static const Color darkSurface = Color(0xFF1F1C17);
  static const Color darkSurfaceAlt = Color(0xFF2A2620);
  static const Color darkBorder = Color(0xFF3A342C);
  static const Color darkTextPrimary = Color(0xFFF5F2EE);
  static const Color darkTextSecondary = Color(0xFFB8B0A6);

  /// Colour for a balance figure: green when they owe us, red when we owe them.
  static Color forBalance(num value, {bool dark = false}) {
    if (value > 0) return dark ? const Color(0xFF4ADE80) : success;
    if (value < 0) return dark ? const Color(0xFFF87171) : danger;
    return dark ? darkTextSecondary : textMuted;
  }

  /// A soft background for [accent] that stays readable in both themes.
  ///
  /// The `*Light` constants are pale, near-white washes designed for a white
  /// page. On a dark page they are almost the brightest thing on screen, and any
  /// text the theme paints on top is *also* near-white — which is how the setup
  /// checklist ended up as invisible text on a cream card. In dark mode the same
  /// idea has to be expressed as a translucent veil of the accent over the dark
  /// surface instead.
  static Color softTint(Color accent, Brightness brightness) =>
      brightness == Brightness.dark
          ? Color.alphaBlend(accent.withValues(alpha: 0.16), darkSurface)
          : Color.alphaBlend(accent.withValues(alpha: 0.14), white);

  /// Text/icon colour to use on top of [softTint] for the same accent.
  static Color onSoftTint(Color accent, Brightness brightness) =>
      brightness == Brightness.dark
          ? Color.alphaBlend(accent.withValues(alpha: 0.85), white)
          : accent;

  /// Chip colours per document status, adapted to the surface behind them.
  static (Color background, Color foreground) forStatus(
    String status, {
    Brightness brightness = Brightness.light,
  }) {
    final accent = switch (status) {
      'paid' => success,
      'partial' => warning,
      'overdue' => danger,
      'cancelled' || 'draft' => brightness == Brightness.dark
          ? darkTextSecondary
          : textSecondary,
      'converted' => info,
      _ => primary,
    };
    return (softTint(accent, brightness), onSoftTint(accent, brightness));
  }

  /// A stable pastel per name, for avatars without a photo.
  static Color forName(String name) {
    const palette = [
      Color(0xFFF97316), Color(0xFF0EA5E9), Color(0xFF8B5CF6), Color(0xFF10B981),
      Color(0xFFEC4899), Color(0xFFF59E0B), Color(0xFF06B6D4), Color(0xFF6366F1),
    ];
    if (name.isEmpty) return palette.first;
    final hash = name.codeUnits.fold<int>(0, (sum, unit) => sum + unit);
    return palette[hash % palette.length];
  }
}
