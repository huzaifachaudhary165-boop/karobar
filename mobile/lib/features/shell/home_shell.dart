import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';
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
  late int _index = widget.initialTab.clamp(0, 3);

  static const _tabs = [
    DashboardScreen(),
    PartiesScreen(),
    InvoicesScreen(),
    ItemsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final strings = context.s;
    final session = ref.watch(sessionProvider);

    return Scaffold(
      appBar: _index == 0 ? _dashboardAppBar(session) : null,
      body: IndexedStack(index: _index, children: _tabs),
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
    final selected = _index == index;
    final color = selected
        ? AppColors.primary
        : Theme.of(context).colorScheme.onSurfaceVariant;

    return Expanded(
      child: InkWell(
        onTap: () => setState(() => _index = index),
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
