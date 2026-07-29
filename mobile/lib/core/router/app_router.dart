import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/assistant/assistant_screen.dart';
import '../../features/assistant/scan_screen.dart';
import '../../features/auth/forgot_password_screen.dart';
import '../../features/auth/login_screen.dart';
import '../../features/auth/register_screen.dart';
import '../../features/auth/splash_screen.dart';
import '../../features/invoices/invoice_detail_screen.dart';
import '../../features/invoices/invoice_form_screen.dart';
import '../../features/expenses/expense_form_screen.dart';
import '../../features/expenses/expenses_screen.dart';
import '../../features/items/item_form_screen.dart';
import '../../features/notifications/notifications_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/parties/party_detail_screen.dart';
import '../../features/parties/party_form_screen.dart';
import '../../features/payments/payments_screen.dart';
import '../../features/reports/reports_screen.dart';
import '../../features/settings/business_settings_screen.dart';
import '../../features/settings/data_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/settings/team_screen.dart';
import '../../features/shell/home_shell.dart';
import '../../providers.dart';

/// Route names, referenced by every `context.goNamed(...)` call.
abstract final class Routes {
  static const splash = 'splash';
  static const onboarding = 'onboarding';
  static const login = 'login';
  static const register = 'register';
  static const forgotPassword = 'forgot-password';
  static const home = 'home';
  static const parties = 'parties';
  static const partyDetail = 'party-detail';
  static const partyForm = 'party-form';
  static const items = 'items';
  static const itemForm = 'item-form';
  static const invoices = 'invoices';
  static const invoiceDetail = 'invoice-detail';
  static const invoiceForm = 'invoice-form';
  static const assistant = 'assistant';
  static const scan = 'scan';
  static const reports = 'reports';
  static const settings = 'settings';
  static const businessSettings = 'business-settings';
  static const team = 'team';
  static const data = 'data';
  static const expenses = 'expenses';
  static const expenseForm = 'expense-form';
  static const payments = 'payments';
  static const notifications = 'notifications';
}

final routerProvider = Provider<GoRouter>((ref) {
  final session = ref.watch(sessionProvider);
  final onboarded = ref.watch(onboardedProvider);

  return GoRouter(
    initialLocation: '/',
    debugLogDiagnostics: false,
    redirect: (context, state) {
      final path = state.matchedLocation;
      // Every screen a signed-out person is allowed to be on. Leaving one out
      // means the redirect below bounces them back to /login the instant they
      // arrive — the screen opens and closes and looks like a dead button.
      const signedOutScreens = {'/login', '/register', '/forgot-password'};
      final onAuthScreen = signedOutScreens.contains(path);

      // Still restoring from disk — hold on the splash.
      if (session.status == AuthStatus.unknown) return path == '/' ? null : '/';

      // First ever launch: the tour comes before the sign-in form.
      if (!onboarded && session.status == AuthStatus.signedOut) {
        return path == '/onboarding' ? null : '/onboarding';
      }
      if (onboarded && path == '/onboarding') return '/login';

      if (session.status == AuthStatus.signedOut) {
        return onAuthScreen ? null : '/login';
      }

      // Signed in but with no business yet: registration finishes the job.
      if (session.needsBusiness && path != '/register') return '/register';

      if (onAuthScreen || path == '/' || path == '/onboarding') return '/home';
      return null;
    },
    routes: [
      GoRoute(
        path: '/',
        name: Routes.splash,
        builder: (_, __) => const SplashScreen(),
      ),
      GoRoute(
        path: '/onboarding',
        name: Routes.onboarding,
        builder: (_, __) => const OnboardingScreen(),
      ),
      GoRoute(
        path: '/login',
        name: Routes.login,
        builder: (_, __) => const LoginScreen(),
      ),
      GoRoute(
        path: '/register',
        name: Routes.register,
        builder: (_, __) => const RegisterScreen(),
      ),
      GoRoute(
        path: '/forgot-password',
        name: Routes.forgotPassword,
        builder: (_, __) => const ForgotPasswordScreen(),
      ),
      GoRoute(
        path: '/home',
        name: Routes.home,
        builder: (_, state) => HomeShell(
          initialTab: int.tryParse(state.uri.queryParameters['tab'] ?? '') ?? 0,
        ),
        routes: [
          GoRoute(
            path: 'parties/new',
            name: Routes.partyForm,
            builder: (_, state) => PartyFormScreen(
              partyId: state.uri.queryParameters['id'],
              initialType: state.uri.queryParameters['type'] ?? 'customer',
            ),
          ),
          GoRoute(
            path: 'parties/:id',
            name: Routes.partyDetail,
            builder: (_, state) => PartyDetailScreen(partyId: state.pathParameters['id']!),
          ),
          GoRoute(
            path: 'items/new',
            name: Routes.itemForm,
            builder: (_, state) => ItemFormScreen(
              itemId: state.uri.queryParameters['id'],
              initialBarcode: state.uri.queryParameters['barcode'],
            ),
          ),
          GoRoute(
            path: 'invoices/new',
            name: Routes.invoiceForm,
            builder: (_, state) => InvoiceFormScreen(
              voucherType: state.uri.queryParameters['type'] ?? 'sale',
              partyId: state.uri.queryParameters['party'],
            ),
          ),
          GoRoute(
            path: 'invoices/:id',
            name: Routes.invoiceDetail,
            builder: (_, state) =>
                InvoiceDetailScreen(voucherId: state.pathParameters['id']!),
          ),
          GoRoute(
            path: 'scan',
            name: Routes.scan,
            builder: (_, __) => const ScanScreen(),
          ),
          GoRoute(
            path: 'reports',
            name: Routes.reports,
            builder: (_, __) => const ReportsScreen(),
          ),
          GoRoute(
            path: 'settings',
            name: Routes.settings,
            builder: (_, __) => const SettingsScreen(),
          ),
          GoRoute(
            path: 'settings/business',
            name: Routes.businessSettings,
            builder: (_, __) => const BusinessSettingsScreen(),
          ),
          GoRoute(
            path: 'settings/team',
            name: Routes.team,
            builder: (_, __) => const TeamScreen(),
          ),
          GoRoute(
            path: 'settings/data',
            name: Routes.data,
            builder: (_, __) => const DataScreen(),
          ),
          GoRoute(
            path: 'expenses',
            name: Routes.expenses,
            builder: (_, __) => const ExpensesScreen(),
          ),
          GoRoute(
            path: 'expenses/new',
            name: Routes.expenseForm,
            builder: (_, __) => const ExpenseFormScreen(),
          ),
          GoRoute(
            path: 'payments',
            name: Routes.payments,
            builder: (_, __) => const PaymentsScreen(),
          ),
          GoRoute(
            path: 'notifications',
            name: Routes.notifications,
            builder: (_, __) => const NotificationsScreen(),
          ),
          GoRoute(
            path: 'assistant',
            name: Routes.assistant,
            builder: (_, state) => AssistantScreen(
              initialPrompt: state.uri.queryParameters['q'],
            ),
          ),
        ],
      ),
    ],
    errorBuilder: (context, state) => Scaffold(
      appBar: AppBar(title: const Text('Not found')),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.explore_off_outlined, size: 48),
            const SizedBox(height: 12),
            Text('No screen at ${state.matchedLocation}'),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => context.goNamed(Routes.home),
              child: const Text('Go home'),
            ),
          ],
        ),
      ),
    ),
  );
});

/// Opens the screen a chat action chip points at.
void openDeepLink(BuildContext context, String? deepLink) {
  if (deepLink == null || deepLink.isEmpty) return;
  final segments = deepLink.split('/').where((s) => s.isNotEmpty).toList();
  if (segments.length < 2) return;

  final id = segments[1];
  switch (segments.first) {
    case 'invoices':
      context.goNamed(Routes.invoiceDetail, pathParameters: {'id': id});
    case 'parties':
      context.goNamed(Routes.partyDetail, pathParameters: {'id': id});
    case 'items':
      context.goNamed(Routes.itemForm, queryParameters: {'id': id});
    case 'payments':
      context.goNamed(Routes.home, queryParameters: {'tab': '3'});
  }
}
