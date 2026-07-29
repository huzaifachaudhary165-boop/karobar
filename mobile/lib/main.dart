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
