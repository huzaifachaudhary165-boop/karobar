import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/data/models.dart';

/// The theme picker's model.
///
/// The accent is only ever a swatch on a card, so a malformed value must never
/// be able to take the picker down — it arrives from a server the app does not
/// control, and a settings screen that crashes cannot be used to fix anything.
void main() {
  group('parsing', () {
    test('a theme parses fully', () {
      final theme = InvoiceTheme.fromJson({
        'key': 'modern_indigo',
        'name': 'Modern — indigo side stripe',
        'layout': 'sidebar',
        'accent': '#4F46E5',
        'paper': 'A4',
        'density': 'regular',
        'is_roll': false,
      });

      expect(theme.key, 'modern_indigo');
      expect(theme.layout, 'sidebar');
      expect(theme.isRoll, isFalse);
      expect(theme.accentValue, 0xFF4F46E5);
    });

    test('a roll theme says so', () {
      final theme = InvoiceTheme.fromJson({
        'key': 'receipt_58',
        'name': 'Receipt — 58mm roll',
        'paper': '58mm auto',
        'is_roll': true,
      });

      expect(theme.isRoll, isTrue);
      expect(theme.paper, '58mm auto');
    });

    test('missing fields fall back rather than crash', () {
      final theme = InvoiceTheme.fromJson({'key': 'x', 'name': 'X'});
      expect(theme.layout, 'band');
      expect(theme.paper, 'A4');
      expect(theme.accentValue, 0xFFF97316);
    });
  });

  group('the accent swatch', () {
    test('a hex colour becomes an opaque colour value', () {
      expect(
        InvoiceTheme.fromJson({'key': 'a', 'name': 'A', 'accent': '#16A34A'}).accentValue,
        0xFF16A34A,
      );
    });

    test('a colour without its hash still reads', () {
      expect(
        InvoiceTheme.fromJson({'key': 'a', 'name': 'A', 'accent': '2563EB'}).accentValue,
        0xFF2563EB,
      );
    });

    test('a malformed colour falls back instead of throwing', () {
      for (final bad in ['', '#', 'orange', '#12', '#GGGGGG', '#1234567890']) {
        expect(
          InvoiceTheme.fromJson({'key': 'a', 'name': 'A', 'accent': bad}).accentValue,
          0xFFF97316,
          reason: 'accent "$bad" should have fallen back',
        );
      }
    });

    test('a black-and-white theme keeps its ink colour', () {
      expect(
        InvoiceTheme.fromJson({'key': 'm', 'name': 'M', 'accent': '#1a1a1a'}).accentValue,
        0xFF1A1A1A,
      );
    });
  });
}
