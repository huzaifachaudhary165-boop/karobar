import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/config/env.dart';
import 'core/router/app_router.dart';
import 'core/storage/token_store.dart';
import 'core/theme/app_theme.dart';
import 'core/widgets/sync_banner.dart';
import 'data/local/app_database.dart';
import 'providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
    ),
  );

  // Loaded up front so the session can be restored before the first frame.
  //
  // Anything thrown before `runApp` means no Flutter frame is ever drawn, and
  // the launch icon stays on screen with no error, no way forward, and nothing
  // to report. An app that cannot start has to say so.
  try {
    final store = await TokenStore.create();
    // Opened lazily inside — this call itself does no disk work.
    final database = AppDatabase();

    runApp(
      ProviderScope(
        overrides: [
          tokenStoreProvider.overrideWithValue(store),
          appDatabaseProvider.overrideWithValue(database),
        ],
        child: const KarobarApp(),
      ),
    );
  } catch (error, stack) {
    debugPrint('startup failed: $error\n$stack');
    runApp(_StartupFailed(error: error));
  }
}

/// Shown when the app could not start at all.
///
/// Rare, and precisely because it is rare it must not present as a frozen logo:
/// that is indistinguishable from a slow phone, and leaves nobody anything to
/// act on or report.
class _StartupFailed extends StatelessWidget {
  const _StartupFailed({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.error_outline, size: 48),
                const SizedBox(height: 16),
                const Text(
                  'Karobar could not start',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Close the app completely and open it again. If it keeps '
                  'happening, reinstall — your data is on the server, not only '
                  'on this phone.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 20),
                SelectableText(
                  '$error',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 11),
                ),
                const SizedBox(height: 10),
                const SelectableText(
                  'Build ${Env.buildStamp}',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class KarobarApp extends ConsumerWidget {
  const KarobarApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final themeMode = ref.watch(themeModeProvider);
    final language = ref.watch(languageProvider);

    return MaterialApp.router(
      title: Env.appName,
      debugShowCheckedModeBanner: false,
      routerConfig: router,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      locale: Locale(language),
      supportedLocales: const [Locale('en'), Locale('ur'), Locale('hi')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      // Roman Urdu/Hindi are written left-to-right, so the app stays LTR even
      // when the locale is `ur`. Only the Urdu wordmark forces RTL.
      builder: (context, child) => Directionality(
        textDirection: TextDirection.ltr,
        child: MediaQuery.withClampedTextScaling(
          minScaleFactor: 0.85,
          maxScaleFactor: 1.35,
          // The sync strip sits above every screen so it is visible wherever
          // the user happens to be when the signal drops.
          child: Column(
            children: [
              if (ref.watch(sessionProvider).status == AuthStatus.signedIn)
                const SyncBanner(),
              Expanded(child: child ?? const SizedBox.shrink()),
            ],
          ),
        ),
      ),
    );
  }
}
