import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers.dart';
import '../auth/google_auth.dart';
import '../router/app_router.dart';
import 'common.dart';

/// "Continue with Google", plus the divider above it.
///
/// Renders nothing when no client id was compiled in — a button that opens a
/// sheet and then fails is worse than no button.
class GoogleButton extends ConsumerStatefulWidget {
  const GoogleButton({super.key, this.enabled = true});

  /// False while another sign-in method on the same screen is mid-flight.
  final bool enabled;

  @override
  ConsumerState<GoogleButton> createState() => _GoogleButtonState();
}

class _GoogleButtonState extends ConsumerState<GoogleButton> {
  bool _busy = false;

  Future<void> _signIn() async {
    setState(() => _busy = true);
    try {
      final signedIn = await ref.read(sessionProvider.notifier).signInWithGoogle();
      if (!mounted) return;
      // Backed out of the picker — say nothing, just return them to the form.
      if (signedIn) context.goNamed(Routes.home);
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!GoogleAuth.isConfigured) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final disabled = _busy || !widget.enabled;

    return Column(
      children: [
        const SizedBox(height: 20),
        Row(
          children: [
            const Expanded(child: Divider()),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Text(
                'or',
                style: theme.textTheme.labelMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ),
            const Expanded(child: Divider()),
          ],
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          onPressed: disabled ? null : _signIn,
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(50),
            side: BorderSide(color: theme.colorScheme.outline),
          ),
          icon: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const _GoogleMark(size: 18),
          label: const Text(
            'Continue with Google',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
      ],
    );
  }
}

/// Google's four-colour G, drawn rather than shipped as an asset — it keeps the
/// APK free of a third-party logo file and stays crisp at any size.
class _GoogleMark extends StatelessWidget {
  const _GoogleMark({this.size = 18});

  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _GooglePainter()),
    );
  }
}

class _GooglePainter extends CustomPainter {
  static const _blue = Color(0xFF4285F4);
  static const _green = Color(0xFF34A853);
  static const _yellow = Color(0xFFFBBC05);
  static const _red = Color(0xFFEA4335);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width;
    final rect = Rect.fromLTWH(0, 0, s, s);
    final stroke = s * 0.22;
    final ring = Rect.fromCircle(center: rect.center, radius: (s - stroke) / 2);

    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.butt;

    // Four arcs, each a quadrant of the ring, in Google's order.
    void arc(double startDegrees, double sweepDegrees, Color color) {
      canvas.drawArc(
        ring,
        startDegrees * 3.1415926535 / 180,
        sweepDegrees * 3.1415926535 / 180,
        false,
        paint..color = color,
      );
    }

    arc(-25, -70, _red);      // top right → top left
    arc(-95, -85, _yellow);   // left
    arc(180, -85, _green);    // bottom
    arc(95, -70, _blue);      // right

    // The horizontal bar of the G.
    canvas.drawRect(
      Rect.fromLTWH(s * 0.50, (s - stroke) / 2, s * 0.50, stroke),
      Paint()..color = _blue,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
