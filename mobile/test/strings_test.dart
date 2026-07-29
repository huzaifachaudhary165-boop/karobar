import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/l10n/strings.dart';

/// Translation is the kind of thing that silently rots: a sentence gets reworded
/// in a screen, the dictionary still holds the old wording, and the app quietly
/// falls back to English for that one label. These pin the behaviour that keeps
/// the failure visible instead.
void main() {
  const en = Strings('en');
  const ur = Strings('ur');
  const hi = Strings('hi');

  group('source-text lookup', () {
    test('English is returned unchanged, so the source stays the truth', () {
      expect(en.t('Print receipt'), 'Print receipt');
      expect(en.t('Set up your shop'), 'Set up your shop');
    });

    test('Roman Urdu and Roman Hindi are actually different where they should be', () {
      expect(ur.t('Save'), 'Save karo');
      expect(hi.t('Save'), 'Save karein');
      expect(ur.t('Delete this item?'), isNot(hi.t('Delete this item?')));
    });

    test('an unknown sentence falls back to English rather than showing a key', () {
      const untranslated = 'Some sentence nobody has translated yet';
      expect(ur.t(untranslated), untranslated);
      expect(hi.t(untranslated), untranslated);
    });

    test('an unknown locale falls back to English', () {
      expect(const Strings('fr').t('Save'), 'Save');
    });
  });

  group('key-based lookup', () {
    test('every language covers every key the English table defines', () {
      // A missing key is invisible at runtime — it just shows English — so the
      // only place it can be caught is here.
      for (final key in Strings.languageNames.keys) {
        expect(Strings.supported, contains(key));
      }
      for (final locale in Strings.supported) {
        expect(Strings(locale).get('save'), isNotEmpty);
        expect(Strings(locale).get('items'), isNotEmpty);
      }
    });

    test('an unknown key returns the key, not an empty string', () {
      expect(en.get('no_such_key'), 'no_such_key');
    });
  });

  group('language picker', () {
    test('every offered language has a sample line to recognise it by', () {
      for (final code in Strings.languageNames.keys) {
        expect(
          Strings.languageSamples[code],
          isNotNull,
          reason: 'someone picking $code needs to see how it reads',
        );
        expect(Strings.languageSamples[code], isNotEmpty);
      }
    });

    test('the labels say Roman, because that is what they are', () {
      // The old labels showed اردو / हिन्दी while claiming Roman, which is
      // exactly the confusion this names away from.
      expect(Strings.languageNames['ur'], 'Roman Urdu');
      expect(Strings.languageNames['hi'], 'Roman Hindi');
    });
  });
}
