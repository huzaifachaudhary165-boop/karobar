import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';
import '../utils/screen.dart';
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
import '../../features/finance/accounts_screen.dart';
import '../../features/finance/cheques_screen.dart';
import '../../features/finance/loans_screen.dart';
import '../../features/items/item_form_screen.dart';
import '../../features/notifications/notifications_screen.dart';
import '../../features/calculator/calculator_screen.dart';
import '../../features/reminders/reminders_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/parties/party_detail_screen.dart';
import '../../features/parties/party_form_screen.dart';
import '../../features/payments/payments_screen.dart';
import '../../features/reports/reports_screen.dart';
import '../../features/settings/business_settings_screen.dart';
import '../../features/loyalty/loyalty_screen.dart';
import '../../features/manufacturing/manufacturing_screen.dart';
import '../../features/pricing/pricing_screen.dart';
import '../../features/recurring/recurring_screen.dart';
import '../../features/tax/tax_screen.dart';
import '../../features/settings/data_screen.dart';
import '../../features/settings/invoice_theme_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/settings/team_screen.dart';
import '../../features/shell/home_shell.dart';
import '../../features/stock/expiry_screen.dart';
import '../../features/stock/godowns_screen.dart';
import '../../features/stock/labels_screen.dart';
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
  static const reminders = 'reminders';
  static const calculator = 'calculator';
  static const godowns = 'godowns';
  static const expiry = 'expiry';
  static const labels = 'labels';
  static const invoiceTheme = 'invoice-theme';
  static const pricing = 'pricing';
  static const recurring = 'recurring';
  static const tax = 'tax';
  static const loyalty = 'loyalty';
  static const manufacturing = 'manufacturing';
  static const accounts = 'accounts';
  static const cheques = 'cheques';
  static const loans = 'loans';
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
        builder: (_, __) => const DesktopFrame(child: SplashScreen()),
      ),
      GoRoute(
        path: '/onboarding',
        name: Routes.onboarding,
        builder: (_, __) => const DesktopFrame(child: OnboardingScreen()),
      ),
      GoRoute(
        path: '/login',
        name: Routes.login,
        builder: (_, __) => const DesktopFrame(child: LoginScreen()),
      ),
      GoRoute(
        path: '/register',
        name: Routes.register,
        builder: (_, __) => const DesktopFrame(child: RegisterScreen()),
      ),
      GoRoute(
        path: '/forgot-password',
        name: Routes.forgotPassword,
        builder: (_, __) => const DesktopFrame(child: ForgotPasswordScreen()),
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
            builder: (_, state) => DesktopFrame(child: PartyFormScreen(
              partyId: state.uri.queryParameters['id'],
              initialType: state.uri.queryParameters['type'] ?? 'customer'),
            ),
          ),
          GoRoute(
            path: 'parties/:id',
            name: Routes.partyDetail,
            builder: (_, state) => DesktopFrame(child: PartyDetailScreen(partyId: state.pathParameters['id']!)),
          ),
          GoRoute(
            path: 'items/new',
            name: Routes.itemForm,
            builder: (_, state) => DesktopFrame(child: ItemFormScreen(
              itemId: state.uri.queryParameters['id'],
              initialBarcode: state.uri.queryParameters['barcode']),
            ),
          ),
          GoRoute(
            path: 'invoices/new',
            name: Routes.invoiceForm,
            builder: (_, state) => DesktopFrame(child: InvoiceFormScreen(
              voucherType: state.uri.queryParameters['type'] ?? 'sale',
              partyId: state.uri.queryParameters['party'],
              // Correcting an existing bill rather than making a new one. Same
              // screen, because the fields are the same and a second one would
              // be a second place for them to drift apart.
              voucherId: state.uri.queryParameters['edit']),
            ),
          ),
          GoRoute(
            path: 'invoices/:id',
            name: Routes.invoiceDetail,
            builder: (_, state) =>
                DesktopFrame(child: InvoiceDetailScreen(voucherId: state.pathParameters['id']!)),
          ),
          GoRoute(
            path: 'scan',
            name: Routes.scan,
            builder: (_, __) => const DesktopFrame(child: ScanScreen()),
          ),
          GoRoute(
            path: 'reports',
            name: Routes.reports,
            builder: (_, __) => const DesktopFrame(child: ReportsScreen()),
          ),
          GoRoute(
            path: 'settings',
            name: Routes.settings,
            builder: (_, __) => const DesktopFrame(child: SettingsScreen()),
          ),
          GoRoute(
            path: 'settings/business',
            name: Routes.businessSettings,
            builder: (_, __) => const DesktopFrame(child: BusinessSettingsScreen()),
          ),
          GoRoute(
            path: 'settings/team',
            name: Routes.team,
            builder: (_, __) => const DesktopFrame(child: TeamScreen()),
          ),
          GoRoute(
            path: 'settings/invoice-look',
            name: Routes.invoiceTheme,
            builder: (_, __) => const DesktopFrame(child: InvoiceThemeScreen()),
          ),
          GoRoute(
            path: 'settings/data',
            name: Routes.data,
            builder: (_, __) => const DesktopFrame(child: DataScreen()),
          ),
          GoRoute(
            path: 'expenses',
            name: Routes.expenses,
            builder: (_, __) => const DesktopFrame(child: ExpensesScreen()),
          ),
          GoRoute(
            path: 'expenses/new',
            name: Routes.expenseForm,
            builder: (_, __) => const DesktopFrame(child: ExpenseFormScreen()),
          ),
          GoRoute(
            path: 'payments',
            name: Routes.payments,
            builder: (_, __) => const DesktopFrame(child: PaymentsScreen()),
          ),
          GoRoute(
            path: 'stock/locations',
            name: Routes.godowns,
            builder: (_, __) => const DesktopFrame(child: GodownsScreen()),
          ),
          GoRoute(
            path: 'stock/expiry',
            name: Routes.expiry,
            builder: (_, __) => const DesktopFrame(child: ExpiryScreen()),
          ),
          GoRoute(
            path: 'stock/labels',
            name: Routes.labels,
            builder: (_, __) => const DesktopFrame(child: LabelsScreen()),
          ),
          GoRoute(
            path: 'pricing',
            name: Routes.pricing,
            builder: (_, __) => const DesktopFrame(child: PricingScreen()),
          ),
          GoRoute(
            path: 'recurring',
            name: Routes.recurring,
            builder: (_, __) => const DesktopFrame(child: RecurringScreen()),
          ),
          GoRoute(
            path: 'tax',
            name: Routes.tax,
            builder: (_, __) => const DesktopFrame(child: TaxScreen()),
          ),
          GoRoute(
            path: 'loyalty',
            name: Routes.loyalty,
            builder: (_, __) => const DesktopFrame(child: LoyaltyScreen()),
          ),
          GoRoute(
            path: 'manufacturing',
            name: Routes.manufacturing,
            builder: (_, __) => const DesktopFrame(child: ManufacturingScreen()),
          ),
          GoRoute(
            path: 'accounts',
            name: Routes.accounts,
            builder: (_, __) => const DesktopFrame(child: AccountsScreen()),
          ),
          GoRoute(
            path: 'cheques',
            name: Routes.cheques,
            builder: (_, __) => const DesktopFrame(child: ChequesScreen()),
          ),
          GoRoute(
            path: 'loans',
            name: Routes.loans,
            builder: (_, __) => const DesktopFrame(child: LoansScreen()),
          ),
          GoRoute(
            path: 'calculator',
            name: Routes.calculator,
            builder: (_, __) => const DesktopFrame(child: CalculatorScreen()),
          ),
          GoRoute(
            path: 'reminders',
            name: Routes.reminders,
            builder: (_, __) => const DesktopFrame(child: RemindersScreen()),
          ),
          GoRoute(
            path: 'notifications',
            name: Routes.notifications,
            builder: (_, __) => const DesktopFrame(child: NotificationsScreen()),
          ),
          GoRoute(
            path: 'assistant',
            name: Routes.assistant,
            builder: (_, state) => DesktopFrame(child: AssistantScreen(
              initialPrompt: state.uri.queryParameters['q']),
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

  // The tab is state, not a destination. Routing to /home?tab=N while already
  // on /home changed the URL and nothing else — go_router reused the shell's
  // State, so the tab index never moved and every tile looked dead.
  ref.read(homeTabProvider.notifier).state = tab;

  // Still navigate, for the case where this is called from a pushed screen —
  // an invoice, a party, settings — which has to be popped to reveal the shell.
  context.goNamed(Routes.home);
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
      // Without a ref the tab cannot be set, so fall back to the URL. Callers
      // that have one — every alert and tile — go through openTab instead.
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
    case 'orders' || 'sale-orders':
      toTab(HomeTab.invoices, voucherType: 'sale_order', voucherFilter: 'all');
    case 'purchase-orders':
      toTab(HomeTab.invoices, voucherType: 'purchase_order', voucherFilter: 'all');
    case 'challans':
      toTab(HomeTab.invoices, voucherType: 'delivery_challan', voucherFilter: 'all');
    case 'payments':
      toTab(HomeTab.parties, partyFilter: 'receivable');

    case 'expiry':
      context.goNamed(Routes.expiry);
    case 'labels' || 'barcodes':
      context.goNamed(Routes.labels);
    case 'locations' || 'godowns':
      context.goNamed(Routes.godowns);
    case 'accounts':
      context.goNamed(Routes.accounts);
    case 'cheques':
      context.goNamed(Routes.cheques);
    case 'loans':
      context.goNamed(Routes.loans);

    default:
      // Never a dead tap: an unknown route lands on the dashboard rather than
      // leaving the person wondering whether they missed the target.
      toTab(HomeTab.dashboard);
  }
}
