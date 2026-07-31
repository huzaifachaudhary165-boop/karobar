import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';
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

/// Every screen a signed-out person is allowed to be on.
///
/// Leaving one out means [resolveRedirect] bounces them back to /login the
/// instant they arrive — the screen opens and closes and looks like a dead
/// button.
const signedOutScreens = {'/login', '/register', '/forgot-password'};

/// Where a request for [path] should actually go, or null to stay put.
///
/// Pulled out of the `GoRouter` closure so it can be tested directly. It is
/// worth testing because a mistake here does not misroute one screen — two
/// rules that disagree send the user back and forth until go_router gives up
/// and shows "No screen at ...", from which every button leads back into the
/// same loop. There is no way out of that except killing the app.
///
/// The rule that makes it safe: **every branch that redirects must first return
/// null for its own destination.** `needsBusiness` broke it by testing
/// `path != '/register'` and then falling through to a later rule that sent
/// /register back to /home, so a signed-in user with no business ping-ponged
/// between the two.
String? resolveRedirect({
  required String path,
  required AuthStatus status,
  required bool onboarded,
  required bool needsBusiness,
}) {
  // Still restoring from disk — hold on the splash.
  if (status == AuthStatus.unknown) return path == '/' ? null : '/';

  // First ever launch: the tour comes before the sign-in form.
  if (!onboarded && status == AuthStatus.signedOut) {
    return path == '/onboarding' ? null : '/onboarding';
  }
  if (onboarded && path == '/onboarding') return '/login';

  if (status == AuthStatus.signedOut) {
    return signedOutScreens.contains(path) ? null : '/login';
  }

  // Signed in, but no shop yet: registration finishes the job, and nothing
  // below may move them off it.
  if (needsBusiness) return path == '/register' ? null : '/register';

  if (signedOutScreens.contains(path) || path == '/' || path == '/onboarding') {
    return '/home';
  }
  return null;
}

final routerProvider = Provider<GoRouter>((ref) {
  final session = ref.watch(sessionProvider);
  final onboarded = ref.watch(onboardedProvider);

  return GoRouter(
    initialLocation: '/',
    debugLogDiagnostics: false,
    redirect: (context, state) => resolveRedirect(
      path: state.matchedLocation,
      status: session.status,
      onboarded: onboarded,
      needsBusiness: session.needsBusiness,
    ),
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
    // This screen is almost never a genuine missing route — go_router also
    // lands here when redirects bounce back and forth past its limit. The old
    // version offered only "Go home", which walked straight back into whatever
    // loop caused it: the app became unusable until it was force-closed.
    //
    // So there is now a second way out that cannot loop, because signing out
    // resets the state the redirects are reading.
    errorBuilder: (context, state) => Scaffold(
      appBar: AppBar(title: Text(context.t('Something went wrong'))),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.explore_off_outlined, size: 48),
              const SizedBox(height: 14),
              Text(
                context.t('This screen could not be opened.'),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 6),
              Text(
                state.matchedLocation,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: () => context.goNamed(Routes.home),
                child: Text(context.t('Go to home')),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: () => ref.read(sessionProvider.notifier).forceSignOut(),
                child: Text(context.t('Sign out and start again')),
              ),
            ],
          ),
        ),
      ),
    ),
  );
});

/// The tabs inside [Routes.home], by the index `?tab=` expects.
///
/// Named because `tab: '1'` scattered through the code is unreadable, and one
/// wrong digit sends someone to the wrong screen with no error to show for it.
abstract final class HomeTab {
  static const dashboard = 0;
  static const parties = 1;
  static const invoices = 2;
  static const items = 3;
}

/// Opens a tab **and applies the filter the caller meant**.
///
/// Sending someone to a list without setting its filter is the shape of bug
/// this exists to stop: tapping "To collect" landed on every party rather than
/// the ones who owe money, and "1 item running low" opened the whole item list
/// rather than the item to reorder. Both looked like dead buttons, because
/// nothing visibly happened.
void openTab(
  BuildContext context,
  WidgetRef ref,
  int tab, {
  String? partyFilter,
  String? itemFilter,
  String? voucherType,
  String? voucherFilter,
}) {
  if (partyFilter != null) {
    ref.read(partyFilterProvider.notifier).state = partyFilter;
  }
  if (itemFilter != null) {
    ref.read(itemFilterProvider.notifier).state = itemFilter;
  }
  if (voucherType != null) {
    ref.read(voucherTypeProvider.notifier).state = voucherType;
  }
  if (voucherFilter != null) {
    ref.read(voucherFilterProvider.notifier).state = voucherFilter;
  }
  context.goNamed(Routes.home, queryParameters: {'tab': '$tab'});
}

/// Opens the screen an alert, notification or chat chip points at.
///
/// Handles both shapes the server sends: `invoices/<id>` for one record, and
/// `/items` for a list. It used to require two segments and return silently
/// otherwise — so every low-stock notification, whose route is just `/items`,
/// was a tap that did nothing at all.
///
/// [ref] is optional only so the chat chips, which have no WidgetRef to hand,
/// can still call this; with it, list routes arrive filtered.
void openDeepLink(BuildContext context, String? deepLink, {WidgetRef? ref}) {
  if (deepLink == null || deepLink.isEmpty) return;

  final withoutQuery = deepLink.split('?').first;
  final segments = withoutQuery.split('/').where((s) => s.isNotEmpty).toList();
  if (segments.isEmpty) return;

  final id = segments.length > 1 ? segments[1] : null;

  void toTab(int tab, {String? partyFilter, String? itemFilter,
      String? voucherType, String? voucherFilter}) {
    if (ref == null) {
      context.goNamed(Routes.home, queryParameters: {'tab': '$tab'});
      return;
    }
    openTab(context, ref, tab,
        partyFilter: partyFilter,
        itemFilter: itemFilter,
        voucherType: voucherType,
        voucherFilter: voucherFilter);
  }

  switch (segments.first) {
    case 'invoices' when id != null:
      context.goNamed(Routes.invoiceDetail, pathParameters: {'id': id});
    case 'invoices':
      toTab(HomeTab.invoices, voucherType: 'sale', voucherFilter: 'all');

    case 'parties' when id != null:
      context.goNamed(Routes.partyDetail, pathParameters: {'id': id});
    case 'parties':
      toTab(HomeTab.parties, partyFilter: 'all');

    case 'items' when id != null:
      context.goNamed(Routes.itemForm, queryParameters: {'id': id});
    case 'items':
      // A low-stock alert means "show me what to reorder", not "show me
      // everything".
      toTab(HomeTab.items, itemFilter: 'low_stock');

    case 'quotations':
      toTab(HomeTab.invoices, voucherType: 'quotation', voucherFilter: 'all');
    case 'payments':
      toTab(HomeTab.parties, partyFilter: 'receivable');

    default:
      // Never a dead tap: an unknown route lands on the dashboard rather than
      // leaving the person wondering whether they missed the target.
      toTab(HomeTab.dashboard);
  }
}
