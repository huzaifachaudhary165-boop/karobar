import 'package:flutter/material.dart';

import '../../core/widgets/karobar_logo.dart';

/// Shown while the session is restored from secure storage.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: BrandBackdrop(
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const KarobarLogo(size: LogoSize.hero, direction: Axis.vertical, onDark: true),
              const SizedBox(height: 48),
              SizedBox(
                width: 26,
                height: 26,
                child: CircularProgressIndicator(
                  strokeWidth: 2.4,
                  color: Colors.white.withValues(alpha: 0.9),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
