import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import '../theme/app_colors.dart';
import 'common.dart';

/// A thin strip that appears only when something is wrong: no signal, work
/// waiting to upload, or a change the server refused.
///
/// It stays out of the way otherwise — a shopkeeper billing a queue of
/// customers should never see chrome about sync.
class SyncBanner extends ConsumerWidget {
  const SyncBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sync = ref.watch(syncStateProvider);
    final controller = ref.read(syncControllerProvider);

    final (visible, tint, icon, message, action) = switch (sync) {
      _ when sync.conflicts.isNotEmpty => (
          true,
          AppColors.danger,
          Icons.error_outline,
          '${sync.conflicts.length} change${sync.conflicts.length == 1 ? '' : 's'} '
              'could not be saved',
          'Review',
        ),
      _ when !sync.online => (
          true,
          AppColors.warning,
          Icons.cloud_off,
          sync.hasPending
              ? 'Offline · ${sync.pending} change${sync.pending == 1 ? '' : 's'} waiting'
              : 'Offline · showing saved data',
          null,
        ),
      _ when sync.syncing => (
          true,
          AppColors.info,
          Icons.sync,
          'Uploading ${sync.pending} change${sync.pending == 1 ? '' : 's'}…',
          null,
        ),
      _ when sync.hasPending => (
          true,
          AppColors.info,
          Icons.cloud_upload_outlined,
          '${sync.pending} change${sync.pending == 1 ? '' : 's'} not uploaded yet',
          'Sync now',
        ),
      _ => (false, AppColors.info, Icons.cloud_done, '', null),
    };

    return AnimatedSize(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOut,
      alignment: Alignment.topCenter,
      child: !visible
          ? const SizedBox(width: double.infinity)
          : Material(
              color: tint.withValues(alpha: 0.12),
              child: SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 7, 8, 7),
                  child: Row(
                    children: [
                      Icon(icon, size: 15, color: tint),
                      const SizedBox(width: 9),
                      Expanded(
                        child: Text(
                          message,
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: tint,
                          ),
                        ),
                      ),
                      if (action != null)
                        TextButton(
                          style: TextButton.styleFrom(
                            foregroundColor: tint,
                            visualDensity: VisualDensity.compact,
                            padding: const EdgeInsets.symmetric(horizontal: 10),
                          ),
                          onPressed: () {
                            if (sync.conflicts.isNotEmpty) {
                              _showConflicts(context, ref);
                            } else {
                              controller.syncNow();
                            }
                          },
                          child: Text(action, style: const TextStyle(fontSize: 12)),
                        ),
                    ],
                  ),
                ),
              ),
            ),
    );
  }

  void _showConflicts(BuildContext context, WidgetRef ref) {
    final controller = ref.read(syncControllerProvider);

    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Changes the server refused',
                style: Theme.of(sheetContext).textTheme.titleLarge,
              ),
              const SizedBox(height: 6),
              Text(
                'These are still saved on this phone. Discard the ones you do '
                'not need, then try again.',
                style: Theme.of(sheetContext).textTheme.bodySmall,
              ),
              const SizedBox(height: 14),
              for (final conflict in controller.state.conflicts)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                conflict.entity,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  fontSize: 13,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                conflict.message,
                                style: const TextStyle(fontSize: 12),
                              ),
                            ],
                          ),
                        ),
                        TextButton(
                          style: TextButton.styleFrom(foregroundColor: AppColors.danger),
                          onPressed: () async {
                            await controller.discard(conflict.clientUuid);
                            if (sheetContext.mounted) Navigator.pop(sheetContext);
                          },
                          child: const Text('Discard'),
                        ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 6),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () {
                    Navigator.pop(sheetContext);
                    controller.syncNow();
                  },
                  child: const Text('Try again'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
