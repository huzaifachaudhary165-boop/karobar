import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';

/// Shown once, on the very first launch.
///
/// The first slide is the language picker rather than a welcome message: a
/// shopkeeper who reads Urdu should see the rest of the tour — and the whole app
/// — in their own language, not after digging through settings.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _controller = PageController();
  int _page = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    // Both, and in this order. Disk is what survives a restart; the provider is
    // what tells the router to stop redirecting here. Writing only to disk is
    // what made this button appear to do nothing at all.
    await ref.read(tokenStoreProvider).setOnboarded(true);
    ref.read(onboardedProvider.notifier).state = true;
    if (mounted) context.go('/login');
  }

  void _next() {
    if (_page >= _slides.length - 1) {
      _finish();
      return;
    }
    _controller.nextPage(
      duration: const Duration(milliseconds: 320),
      curve: Curves.easeOutCubic,
    );
  }

  late final List<_Slide> _slides = [
    const _Slide(
      art: _LanguageArt(),
      title: {
        'en': 'Welcome to Karobar',
        'ur': 'Karobar mein khush aamdeed',
        'hi': 'Karobar mein swagat hai',
      },
      body: {
        'en': 'Billing, stock and accounts for your shop.\nPick the language you are most comfortable in.',
        'ur': 'Aap ki dukan ki billing, stock aur hisab.\nApni pasand ki zaban chunein.',
        'hi': 'Aapki dukan ki billing, stock aur hisab.\nApni pasand ki bhasha chunein.',
      },
      isLanguagePicker: true,
    ),
    const _Slide(
      art: _BillingArt(),
      title: {
        'en': 'Bills in ten seconds',
        'ur': 'Das second mein bill',
        'hi': 'Das second mein bill',
      },
      body: {
        'en': 'Pick a customer, add items, done. Stock and the customer’s balance update themselves.',
        'ur': 'Customer chunein, item daalein, bas. Stock aur customer ka baqi khud update ho jata hai.',
        'hi': 'Customer chunein, item daalein, bas. Stock aur customer ka bakaya khud update ho jata hai.',
      },
    ),
    const _Slide(
      art: _AssistantArt(),
      title: {
        'en': 'Just say it',
        'ur': 'Bas keh dein',
        'hi': 'Bas keh dein',
      },
      body: {
        'en': '“Ahmed ko 5 bori cement becha 1290 ka” — the assistant creates the invoice for you, in your own words.',
        'ur': '“Ahmed ko 5 bori cement becha 1290 ka” — assistant aap ki baat samajh kar bill bana deta hai.',
        'hi': '“Ahmed ko 5 bori cement becha 1290 ka” — assistant aapki baat samajh kar bill bana deta hai.',
      },
    ),
    const _Slide(
      art: _ScanArt(),
      title: {
        'en': 'Snap a supplier bill',
        'ur': 'Supplier ka bill photo karein',
        'hi': 'Supplier ka bill photo karein',
      },
      body: {
        'en': 'Photograph the bill and the items, rates and totals are read for you. You check it before it is saved.',
        'ur': 'Bill ki photo lein, items aur rate khud parh liye jate hain. Save se pehle aap check kar lein.',
        'hi': 'Bill ki photo lein, items aur rate khud padh liye jate hain. Save se pehle aap check kar lein.',
      },
    ),
    const _Slide(
      art: _OfflineArt(),
      title: {
        'en': 'Works without internet',
        'ur': 'Internet ke baghair bhi chalta hai',
        'hi': 'Internet ke bina bhi chalta hai',
      },
      body: {
        'en': 'Keep billing when the signal drops. Everything syncs the moment you are back online.',
        'ur': 'Signal na ho to bhi billing jari rakhein. Wapas online hote hi sab sync ho jata hai.',
        'hi': 'Signal na ho to bhi billing jari rakhein. Wapas online hote hi sab sync ho jata hai.',
      },
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final language = ref.watch(languageProvider);
    final theme = Theme.of(context);
    final isLast = _page == _slides.length - 1;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 12, 0),
              child: Row(
                children: [
                  const KarobarLogo(size: LogoSize.small, showSubtitle: false),
                  const Spacer(),
                  if (!isLast)
                    TextButton(
                      onPressed: _finish,
                      child: Text(switch (language) {
                        'ur' => 'Chhorein',
                        'hi' => 'Chhodein',
                        _ => 'Skip',
                      }),
                    ),
                ],
              ),
            ),

            Expanded(
              child: PageView.builder(
                controller: _controller,
                onPageChanged: (index) => setState(() => _page = index),
                itemCount: _slides.length,
                itemBuilder: (_, index) => _SlideView(
                  slide: _slides[index],
                  language: language,
                  onLanguageChanged: (code) =>
                      ref.read(languageProvider.notifier).set(code),
                ),
              ),
            ),

            Padding(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      for (var index = 0; index < _slides.length; index++)
                        AnimatedContainer(
                          duration: const Duration(milliseconds: 240),
                          margin: const EdgeInsets.symmetric(horizontal: 3),
                          width: index == _page ? 22 : 7,
                          height: 7,
                          decoration: BoxDecoration(
                            color: index == _page
                                ? AppColors.primary
                                : theme.colorScheme.outline,
                            borderRadius: BorderRadius.circular(999),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 22),
                  FilledButton(
                    onPressed: _next,
                    child: Text(
                      isLast
                          ? switch (language) {
                              'ur' => 'Shuru karein',
                              'hi' => 'Shuru karein',
                              _ => 'Get started',
                            }
                          : switch (language) {
                              'ur' => 'Aagey',
                              'hi' => 'Aage',
                              _ => 'Next',
                            },
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Slide {
  const _Slide({
    required this.art,
    required this.title,
    required this.body,
    this.isLanguagePicker = false,
  });

  final Widget art;
  final Map<String, String> title;
  final Map<String, String> body;
  final bool isLanguagePicker;

  String titleFor(String language) => title[language] ?? title['en']!;
  String bodyFor(String language) => body[language] ?? body['en']!;
}

class _SlideView extends StatelessWidget {
  const _SlideView({
    required this.slide,
    required this.language,
    required this.onLanguageChanged,
  });

  final _Slide slide;
  final String language;
  final ValueChanged<String> onLanguageChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Column(
        children: [
          const SizedBox(height: 12),
          SizedBox(height: 220, child: Center(child: slide.art)),
          const SizedBox(height: 32),
          Text(
            slide.titleFor(language),
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 10),
          Text(
            slide.bodyFor(language),
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyLarge?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              height: 1.55,
            ),
          ),
          if (slide.isLanguagePicker) ...[
            const SizedBox(height: 24),
            for (final entry in Strings.languageNames.entries)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _LanguageOption(
                  code: entry.key,
                  label: entry.value,
                  sample: Strings.languageSamples[entry.key] ?? '',
                  selected: language == entry.key,
                  onTap: () => onLanguageChanged(entry.key),
                ),
              ),
          ],
          const SizedBox(height: 12),
        ],
      ),
    );
  }
}

class _LanguageOption extends StatelessWidget {
  const _LanguageOption({
    required this.code,
    required this.label,
    required this.sample,
    required this.selected,
    required this.onTap,
  });

  final String code;
  final String label;
  final String sample;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // primaryDarker is unreadable on the dark tint; this picks the right one.
    final onTint = AppColors.onSoftTint(AppColors.primary, theme.brightness);

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppTheme.radius),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: selected ? AppColors.softTint(AppColors.primary, Theme.of(context).brightness) : theme.colorScheme.surface,
          borderRadius: BorderRadius.circular(AppTheme.radius),
          border: Border.all(
            color: selected ? AppColors.primary : theme.colorScheme.outline,
            width: selected ? 1.8 : 1,
          ),
        ),
        child: Row(
          children: [
            Text(
              switch (code) {
                'ur' => 'اردو',
                'hi' => 'हिन्दी',
                _ => 'A',
              },
              style: TextStyle(
                fontSize: 19,
                fontWeight: FontWeight.w700,
                color: selected ? onTint : theme.colorScheme.onSurface,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    label,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                      color: selected ? onTint : null,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    sample,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            if (selected)
              const Icon(Icons.check_circle, color: AppColors.primary, size: 21),
          ],
        ),
      ),
    );
  }
}

// ── illustrations ────────────────────────────────────────────────
// Drawn from theme colours rather than shipped as images: they stay sharp at
// every density, respond to dark mode, and add nothing to the download size.

class _ArtFrame extends StatelessWidget {
  const _ArtFrame({required this.child, this.tint = AppColors.primary});

  final Widget child;
  final Color tint;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 200,
      height: 200,
      decoration: BoxDecoration(
        color: tint.withValues(alpha: 0.09),
        borderRadius: BorderRadius.circular(52),
      ),
      alignment: Alignment.center,
      child: child,
    );
  }
}

class _LanguageArt extends StatelessWidget {
  const _LanguageArt();

  @override
  Widget build(BuildContext context) {
    return _ArtFrame(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const KarobarMark(size: 74),
          const SizedBox(height: 16),
          Directionality(
            textDirection: TextDirection.rtl,
            child: Text(
              'کاروبار',
              style: TextStyle(
                fontSize: 28,
                height: 1.7,
                fontWeight: FontWeight.w700,
                color: Theme.of(context).colorScheme.onSurface,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _BillingArt extends StatelessWidget {
  const _BillingArt();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return _ArtFrame(
      child: Container(
        width: 122,
        height: 152,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: scheme.surface,
          borderRadius: BorderRadius.circular(16),
          boxShadow: [
            BoxShadow(
              color: AppColors.primary.withValues(alpha: 0.16),
              blurRadius: 22,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _Bar(width: 54, color: AppColors.primary),
            const SizedBox(height: 12),
            for (var index = 0; index < 4; index++) ...[
              Row(
                children: [
                  _Bar(width: 40, color: scheme.outline),
                  const Spacer(),
                  _Bar(width: 22, color: scheme.outline),
                ],
              ),
              const SizedBox(height: 9),
            ],
            const Spacer(),
            Row(
              children: [
                _Bar(width: 30, color: scheme.outline),
                const Spacer(),
                const _Bar(width: 42, color: AppColors.success, height: 9),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _AssistantArt extends StatelessWidget {
  const _AssistantArt();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return _ArtFrame(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Align(
            alignment: Alignment.centerRight,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: const BoxDecoration(
                color: AppColors.primary,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(14),
                  topRight: Radius.circular(14),
                  bottomLeft: Radius.circular(14),
                  bottomRight: Radius.circular(4),
                ),
              ),
              child: const Text(
                'Ahmed ko 5 bori\ncement becha',
                style: TextStyle(color: Colors.white, fontSize: 11.5, height: 1.35),
              ),
            ),
          ),
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerLeft,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: AppColors.softTint(AppColors.success, Theme.of(context).brightness),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: AppColors.success.withValues(alpha: 0.35)),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.check_circle, size: 13, color: AppColors.success),
                  SizedBox(width: 6),
                  Text(
                    'INV-0042 · Rs 6,450',
                    style: TextStyle(
                      color: AppColors.success,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: scheme.surface,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: AppColors.primary.withValues(alpha: 0.22),
                  blurRadius: 18,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: const Icon(Icons.mic, color: AppColors.primary, size: 24),
          ),
        ],
      ),
    );
  }
}

class _ScanArt extends StatelessWidget {
  const _ScanArt();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return _ArtFrame(
      tint: AppColors.warning,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Transform.rotate(
            angle: -0.10,
            child: Container(
              width: 108,
              height: 138,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: scheme.surface,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.10),
                    blurRadius: 18,
                    offset: const Offset(0, 6),
                  ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (var index = 0; index < 6; index++) ...[
                    _Bar(width: index.isEven ? 62 : 44, color: scheme.outline, height: 5),
                    const SizedBox(height: 8),
                  ],
                ],
              ),
            ),
          ),
          // Scan frame corners.
          const SizedBox(
            width: 148,
            height: 148,
            child: CustomPaint(painter: _ScanFramePainter(AppColors.warning)),
          ),
          Positioned(
            bottom: 26,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
              decoration: BoxDecoration(
                color: AppColors.warning,
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Text(
                '12 items read',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ScanFramePainter extends CustomPainter {
  const _ScanFramePainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.4
      ..strokeCap = StrokeCap.round;

    const arm = 26.0;
    final w = size.width;
    final h = size.height;

    // Four corner brackets.
    canvas
      ..drawPath(Path()..moveTo(0, arm)..lineTo(0, 0)..lineTo(arm, 0), paint)
      ..drawPath(Path()..moveTo(w - arm, 0)..lineTo(w, 0)..lineTo(w, arm), paint)
      ..drawPath(Path()..moveTo(w, h - arm)..lineTo(w, h)..lineTo(w - arm, h), paint)
      ..drawPath(Path()..moveTo(arm, h)..lineTo(0, h)..lineTo(0, h - arm), paint);
  }

  @override
  bool shouldRepaint(_ScanFramePainter oldDelegate) => oldDelegate.color != color;
}

class _OfflineArt extends StatelessWidget {
  const _OfflineArt();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return _ArtFrame(
      tint: AppColors.info,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 76,
            height: 130,
            decoration: BoxDecoration(
              color: scheme.surface,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: scheme.outline, width: 2),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.cloud_off_outlined, size: 26, color: AppColors.info),
                const SizedBox(height: 8),
                _Bar(width: 40, color: scheme.outline, height: 5),
                const SizedBox(height: 6),
                _Bar(width: 28, color: scheme.outline, height: 5),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
            decoration: BoxDecoration(
              color: AppColors.info,
              borderRadius: BorderRadius.circular(999),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.sync, size: 13, color: Colors.white),
                SizedBox(width: 6),
                Text(
                  'Syncs later',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.width, required this.color, this.height = 6});

  final double width;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(999),
      ),
    );
  }
}
