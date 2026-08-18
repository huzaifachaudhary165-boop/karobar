import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/screen.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';
import '../calculator/calculator_screen.dart';
import '../dashboard/dashboard_screen.dart';
import '../invoices/invoices_screen.dart';
import '../items/items_screen.dart';
import '../parties/parties_screen.dart';

/// Bottom-tab shell. The assistant sits in the centre as a raised button because
/// it is the fastest route to almost every task in the app.
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key, this.initialTab = 0});

  final int initialTab;

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  /// The calculator is a destination like any other rather than something
  /// tucked into the rail, because that is how a shopkeeper reaches for it —
  /// the same tap as Invoices, and the whole module when it opens.
  static const _tabs = [
    DashboardScreen(),
    PartiesScreen(),
    InvoicesScreen(),
    ItemsScreen(),
    CalculatorScreen(),
  ];

  /// The last index the bottom bar can show.
  ///
  /// A phone keeps four: a fifth tab crowds a bar that is already at the
  /// bottom of a small screen, and the dashboard has a calculator tile.
  static const _lastCompactTab = 3;
  static const _lastTab = 4;

  @override
  void initState() {
    super.initState();
    // Seeds the shared tab from the route, for a deep link arriving at a
    // particular list.
    if (widget.initialTab != 0) {
      Future.microtask(() {
        if (mounted) {
          ref.read(homeTabProvider.notifier).state =
              widget.initialTab.clamp(0, _lastTab);
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final strings = context.s;
    final session = ref.watch(sessionProvider);
    // Watched, not held in a `late` field. Read once into local state, moving
    // between tabs from inside the app did nothing at all: /home to
    // /home?tab=1 reuses the same State, so the field never changed and every
    // dashboard tile, alert and assistant link looked like a dead button.
    // Clamped differently per layout: the rail has five destinations, the
    // bottom bar four. Letting a phone land on tab 4 would show the calculator
    // with no tab selected and no way back to it.
    final wide = context.screen.usesSideRail;
    final index = ref
        .watch(homeTabProvider)
        .clamp(0, wide ? _lastTab : _lastCompactTab);

    // A bottom bar down the full width of a desktop window puts the tabs at
    // the furthest point from where anyone is looking, a hand's width apart.
    // The same four destinations go down the side instead, where every other
    // application on that screen keeps them.
    if (wide) {
      return Scaffold(
        appBar: index == 0 ? _dashboardAppBar(session) : null,
        body: Row(
          children: [
            _SideRail(
              index: index,
              onSelect: (i) => ref.read(homeTabProvider.notifier).state = i,
              labels: strings,
            ),
            const VerticalDivider(width: 1, thickness: 1),
            // Capped rather than stretched. A bill row spread across 1900
            // pixels puts the customer's name and the amount at opposite ends
            // of the desk, and the eye cannot carry a row that far.
            Expanded(
              child: ReadableWidth(
                maxWidth: 1200,
                padHorizontally: false,
                child: IndexedStack(index: index, children: _tabs),
              ),
            ),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: index == 0 ? _dashboardAppBar(session) : null,
      body: IndexedStack(index: index, children: _tabs),
      floatingActionButton: FloatingActionButton(
        heroTag: 'assistant',
        onPressed: () => context.goNamed(Routes.assistant),
        shape: const CircleBorder(),
        tooltip: strings.get('assistant'),
        child: const Icon(Icons.auto_awesome, size: 26),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
      bottomNavigationBar: BottomAppBar(
        height: 64,
        padding: EdgeInsets.zero,
        notchMargin: 8,
        shape: const CircularNotchedRectangle(),
        color: Theme.of(context).colorScheme.surface,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _navItem(0, Icons.dashboard_outlined, Icons.dashboard, strings.get('home')),
            _navItem(1, Icons.people_outline, Icons.people, strings.get('parties')),
            const SizedBox(width: 56), // notch for the assistant button
            _navItem(2, Icons.receipt_long_outlined, Icons.receipt_long,
                strings.get('invoices')),
            _navItem(3, Icons.inventory_2_outlined, Icons.inventory_2, strings.get('items')),
          ],
        ),
      ),
    );
  }

  PreferredSizeWidget _dashboardAppBar(SessionState session) {
    return AppBar(
      titleSpacing: 16,
      title: Row(
        children: [
          const KarobarMark(size: 30),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  session.business?.name ?? 'Karobar',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
                ),
                Text(
                  session.user?.name ?? '',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 11,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      actions: [
        // Scan and Reports also live in the dashboard's quick actions, so the
        // bar keeps only the two things you reach for from anywhere.
        _NotificationBell(),
        IconButton(
          icon: const Icon(Icons.settings_outlined),
          tooltip: context.t('Settings'),
          onPressed: () => context.goNamed(Routes.settings),
        ),
        const SizedBox(width: 4),
      ],
    );
  }

  Widget _navItem(int index, IconData icon, IconData activeIcon, String label) {
    final selected = ref.watch(homeTabProvider) == index;
    final color = selected
        ? AppColors.primary
        : Theme.of(context).colorScheme.onSurfaceVariant;

    return Expanded(
      child: InkWell(
        onTap: () => ref.read(homeTabProvider.notifier).state = index,
        borderRadius: BorderRadius.circular(12),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(selected ? activeIcon : icon, size: 22, color: color),
            const SizedBox(height: 2),
            Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 10.5,
                color: color,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The four destinations, down the side, for a window wide enough to have one.
///
/// The assistant keeps its raised button rather than becoming a fifth row: it
/// is the fastest route to almost everything in the app, and demoting it to a
/// list entry on the screen where people have the most room to work would be
/// exactly backwards.
class _SideRail extends StatelessWidget {
  const _SideRail({
    required this.index,
    required this.onSelect,
    required this.labels,
  });

  final int index;
  final ValueChanged<int> onSelect;
  final Strings labels;

  @override
  Widget build(BuildContext context) {
    // Deliberately not extended. An extended rail is 250-odd pixels of mostly
    // empty space for four destinations, and it was the first thing that
    // looked wrong on a real screen. Icon over label is the compact form, and
    // it reads at a glance without eating a seventh of the window.
    //
    // No logo either: the app bar already carries the shop's name and mark
    // directly above this, and two of them a centimetre apart is one too many.
    // Wide enough for a four-column keypad and no wider. The rail was 84 and
    // the space under the destinations ran empty to the bottom of the window;
    // a shopkeeper on a laptop keeps a calculator open beside their work
    // anyway, so it goes there rather than nowhere.
    return NavigationRail(
      selectedIndex: index,
      onDestinationSelected: onSelect,
      labelType: NavigationRailLabelType.all,
      minWidth: 92,
      groupAlignment: -1,
      leading: Padding(
        padding: const EdgeInsets.only(top: 12, bottom: 6),
        child: FloatingActionButton.small(
          heroTag: 'assistant',
          onPressed: () => context.goNamed(Routes.assistant),
          shape: const CircleBorder(),
          elevation: 1,
          tooltip: labels.get('assistant'),
          child: const Icon(Icons.auto_awesome, size: 20),
        ),
      ),
      destinations: [
        NavigationRailDestination(
          icon: const Icon(Icons.dashboard_outlined),
          selectedIcon: const Icon(Icons.dashboard),
          label: Text(labels.get('home')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.people_outline),
          selectedIcon: const Icon(Icons.people),
          label: Text(labels.get('parties')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.receipt_long_outlined),
          selectedIcon: const Icon(Icons.receipt_long),
          label: Text(labels.get('invoices')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.inventory_2_outlined),
          selectedIcon: const Icon(Icons.inventory_2),
          label: Text(labels.get('items')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.calculate_outlined),
          selectedIcon: const Icon(Icons.calculate),
          label: Text(labels.get('calculator')),
        ),
      ],
    );
  }
}

/// Bell with an unread count. The count is derived server-side from live state,
/// so it drops on its own once a bill gets paid or an item is restocked.
class _NotificationBell extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // valueOrNull keeps the last count while a refresh is in flight. Treating
    // "loading" as zero made the badge blink off and back on after every write.
    final count = ref.watch(unreadCountProvider).valueOrNull ?? 0;

    return Stack(
      alignment: Alignment.center,
      children: [
        IconButton(
          icon: const Icon(Icons.notifications_outlined),
          tooltip: context.t('Alerts'),
          onPressed: () => context.goNamed(Routes.notifications),
        ),
        if (count > 0)
          Positioned(
            top: 8,
            right: 6,
            child: IgnorePointer(child: CountBadge(count)),
          ),
      ],
    );
  }
}
