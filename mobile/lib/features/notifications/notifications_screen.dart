import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// What needs attention today.
///
/// The list is recomputed server-side on open rather than accumulated, so a
/// reminder for an invoice that has since been paid is simply gone.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(notificationsProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Alerts')),
        actions: [
          async.maybeWhen(
            data: (rows) => rows.any((n) => !n.isRead)
                ? TextButton(
                    onPressed: () async {
                      await ref.read(notificationRepositoryProvider).markAllRead();
                      ref.invalidate(notificationsProvider);
                      ref.invalidate(unreadCountProvider);
                    },
                    child: Text(context.t('Mark all read')),
                  )
                : const SizedBox.shrink(),
            orElse: () => const SizedBox.shrink(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(notificationsProvider);
          ref.invalidate(unreadCountProvider);
        },
        child: async.when(
          loading: () => const ListSkeleton(rows: 5, height: 84),
          error: (error, _) => EmptyState(
            title: 'Could not load alerts',
            message: error.toString(),
            isError: true,
            actionLabel: 'Retry',
            onAction: () => ref.invalidate(notificationsProvider),
          ),
          data: (rows) => rows.isEmpty
              ? const EmptyState(
                  title: 'Nothing needs attention',
                  message: 'No overdue payments, no low stock, no pending quotations.',
                  icon: Icons.check_circle_outline,
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                  children: [
                    for (final group in _groupByKind(rows).entries) ...[
                      Padding(
                        padding: const EdgeInsets.fromLTRB(2, 8, 2, 8),
                        child: Text(
                          '${_kindLabel(group.key)} · ${group.value.length}',
                          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                        ),
                      ),
                      for (final notification in group.value)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: _NotificationRow(notification: notification),
                        ),
                    ],
                  ],
                ),
        ),
      ),
    );
  }

  Map<String, List<AppNotification>> _groupByKind(List<AppNotification> rows) {
    // Fixed order: money first, then stock, then follow-ups.
    const order = ['payment_due', 'low_stock', 'expiring_stock', 'stale_quotation'];
    final groups = <String, List<AppNotification>>{};
    for (final kind in order) {
      final matching = rows.where((n) => n.kind == kind).toList();
      if (matching.isNotEmpty) groups[kind] = matching;
    }
    final others = rows.where((n) => !order.contains(n.kind)).toList();
    if (others.isNotEmpty) groups['other'] = others;
    return groups;
  }

  String _kindLabel(String kind) => switch (kind) {
        'payment_due' => 'Overdue payments',
        'low_stock' => 'Running low',
        'expiring_stock' => 'Expiring soon',
        'stale_quotation' => 'Awaiting a reply',
        _ => 'Other',
      };
}

class _NotificationRow extends ConsumerWidget {
  const _NotificationRow({required this.notification});

  final AppNotification notification;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final (tint, icon) = switch (notification.kind) {
      'payment_due' => (AppColors.danger, Icons.schedule),
      'low_stock' => (AppColors.warning, Icons.inventory_2_outlined),
      'expiring_stock' => (AppColors.warning, Icons.event_busy_outlined),
      'stale_quotation' => (AppColors.info, Icons.request_quote_outlined),
      _ => (AppColors.primary, Icons.notifications_outlined),
    };

    return AppCard(
      color: notification.isRead ? null : tint.withValues(alpha: 0.05),
      borderColor: notification.isRead ? null : tint.withValues(alpha: 0.30),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () async {
        if (!notification.isRead) {
          await ref.read(notificationRepositoryProvider).markRead(notification.id);
          ref.invalidate(unreadCountProvider);
        }
        if (context.mounted) openDeepLink(context, notification.route);
      },
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: tint.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 17, color: tint),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  notification.title,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: notification.isRead ? FontWeight.w600 : FontWeight.w800,
                  ),
                ),
                if (notification.body != null) ...[
                  const SizedBox(height: 3),
                  Text(
                    notification.body!,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
                if (notification.createdAt != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    Fmt.relative(notification.createdAt),
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
              ],
            ),
          ),
          if (!notification.isRead)
            Container(
              margin: const EdgeInsets.only(top: 4, left: 6),
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: tint, shape: BoxShape.circle),
            ),
        ],
      ),
    );
  }
}
