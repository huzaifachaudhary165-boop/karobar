import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/theme/app_colors.dart';
import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../providers.dart';

/// Your data, in your hands: take a copy, put one back, or hand the tax office
/// the file it asks for.
class DataScreen extends ConsumerStatefulWidget {
  const DataScreen({super.key});

  @override
  ConsumerState<DataScreen> createState() => _DataScreenState();
}

class _DataScreenState extends ConsumerState<DataScreen> {
  String? _busy;

  Future<void> _run(String key, Future<void> Function() action) async {
    setState(() => _busy = key);
    try {
      await action();
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _backup() => _run('backup', () async {
        final result = await ref.read(dataRepositoryProvider).backup();
        if (!mounted) return;
        // Handed to the share sheet rather than written somewhere the user has
        // to go hunting for: they pick Drive, WhatsApp, email — wherever they
        // already keep things.
        await Share.shareXFiles(
          [
            XFile.fromData(
              Uint8List.fromList(result.bytes),
              name: result.filename,
              mimeType: 'application/json',
            ),
          ],
          subject: 'Karobar backup',
          // fileNameOverrides: XFile.fromData ignores `name` on mobile, so the
          // share sheet would otherwise offer an unnamed temp file.
          fileNameOverrides: [result.filename],
        );

        // Recorded after the sheet closes rather than before it opens: a
        // shopkeeper who backs out of the share sheet has not backed anything
        // up, and telling them they have is the one thing this must not do.
        await ref.read(tokenStoreProvider).setLastBackupAt(DateTime.now());
        if (mounted) setState(() {});
      });

  Future<void> _restore() => _run('restore', () async {
        final picked = await FilePicker.pickFiles(
          type: FileType.custom,
          allowedExtensions: ['json'],
          withData: true,
        );
        final file = picked?.files.firstOrNull;
        final bytes = file?.bytes;
        // Both null-checked together so `file` is promoted for the rest of the
        // method — the picker returns null when the user backs out.
        if (file == null || bytes == null) return;

        if (!mounted) return;
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(context.t('Restore this backup?')),
            content: Text(
              'Anything already in your shop is left exactly as it is — only '
              'records missing from it are added back.\n\n${file.name}',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: Text(context.t('Cancel')),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(dialogContext, true),
                child: Text(context.t('Restore')),
              ),
            ],
          ),
        );
        if (confirmed != true) return;

        final result =
            await ref.read(dataRepositoryProvider).restore(bytes, file.name);
        if (!mounted) return;
        invalidateBusinessData(ref);
        showSuccess(context, '${result['total']} record(s) restored.');
      });

  Future<void> _gstr1() => _run('gstr1', () async {
        final now = DateTime.now();
        final range = await showDateRangePicker(
          context: context,
          firstDate: DateTime(now.year - 3),
          lastDate: now,
          initialDateRange: DateTimeRange(
            start: DateTime(now.year, now.month, 1),
            end: now,
          ),
          helpText: 'Which period?',
        );
        if (range == null) return;

        final csv = await ref.read(dataRepositoryProvider).gstr1Csv(
              start: range.start,
              end: range.end,
            );
        if (!mounted) return;

        final name = 'gstr1-${Fmt.iso(range.start)}-to-${Fmt.iso(range.end)}.csv';
        await Share.shareXFiles(
          [
            XFile.fromData(
              Uint8List.fromList(utf8.encode(csv)),
              name: name,
              mimeType: 'text/csv',
            ),
          ],
          subject: 'GSTR-1',
          fileNameOverrides: [name],
        );
      });

  Future<void> _clear() => _run('clear', () async {
        final typed = TextEditingController();
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(context.t('Delete all transactions?')),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Every bill, payment and expense is removed. Your customers, '
                  'items and settings stay.\n\nThis cannot be undone — take a '
                  'backup first.\n\nType DELETE to confirm:',
                ),
                const SizedBox(height: 12),
                TextField(controller: typed, autofocus: true),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: Text(context.t('Cancel')),
              ),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: Text(context.t('Delete')),
              ),
            ],
          ),
        );
        // Typing the word is the guard, not the button — a mis-tap cannot do this.
        if (confirmed != true || typed.text.trim().toUpperCase() != 'DELETE') return;

        final message = await ref.read(dataRepositoryProvider).clearTransactions();
        if (!mounted) return;
        invalidateBusinessData(ref);
        showSuccess(context, message);
      });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // GST is what makes the GSTR-1 export relevant, not the country label —
    // and the currency is the field the session actually carries.
    final currency = ref.watch(sessionProvider).business?.currency ?? '';
    final isIndia = currency.toUpperCase() == 'INR';

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Your data'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          AppCard(
            color: AppColors.softTint(AppColors.primary, theme.brightness),
            borderColor: AppColors.primary.withValues(alpha: 0.28),
            child: Row(
              children: [
                Icon(Icons.lock_outline,
                    size: 20,
                    color: AppColors.onSoftTint(AppColors.primary, theme.brightness)),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    'A backup is a plain file you can open, keep anywhere, and '
                    'load back. Nothing here locks your records to this app.',
                    style: theme.textTheme.bodySmall?.copyWith(height: 1.45),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // When the last one was taken, and a nudge when it was not recent.
          // A shop that has never backed up does not know that about itself,
          // and the day they find out is the day it would have mattered.
          _LastBackup(at: ref.read(tokenStoreProvider).lastBackupAt),

          const SizedBox(height: 12),

          _Action(
            icon: Icons.download_outlined,
            title: 'Back up everything',
            subtitle: 'Customers, items, bills, payments and expenses in one file',
            busy: _busy == 'backup',
            onTap: _backup,
          ),
          _Action(
            icon: Icons.upload_outlined,
            title: 'Restore from a backup',
            subtitle: 'Adds anything missing; never overwrites what you have',
            busy: _busy == 'restore',
            onTap: _restore,
          ),

          if (isIndia)
            _Action(
              icon: Icons.receipt_long_outlined,
              title: 'GSTR-1 export',
              subtitle: 'A spreadsheet of the period, ready for the GST portal',
              busy: _busy == 'gstr1',
              onTap: _gstr1,
            ),

          const SizedBox(height: 8),
          const Divider(),
          const SizedBox(height: 8),

          _Action(
            icon: Icons.delete_sweep_outlined,
            title: 'Delete all transactions',
            subtitle: 'Start a fresh year. Customers and items are kept',
            danger: true,
            busy: _busy == 'clear',
            onTap: _clear,
          ),

          if (isIndia) ...[
            const SizedBox(height: 20),
            Text(
              'The GSTR-1 file is prepared for you to upload to the GST portal '
              'yourself. Filing directly from an app needs a licensed GSP, which '
              'no free tool can offer.',
              style: theme.textTheme.labelSmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                height: 1.5,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// When the last backup was taken, and a nudge when it was not recent.
///
/// A shop that has never backed up does not know that about itself, and the
/// day they find out is the day it would have mattered. The line is quiet once
/// a backup is recent and only becomes a warning when it stops being.
class _LastBackup extends StatelessWidget {
  const _LastBackup({required this.at});

  final DateTime? at;

  /// Past this, a backup is old enough to be worth saying so about.
  static const _staleAfterDays = 14;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final when = at;
    final days = when == null ? null : DateTime.now().difference(when).inDays;
    final stale = days == null || days >= _staleAfterDays;

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      borderColor: stale ? AppColors.warning.withValues(alpha: 0.5) : null,
      child: Row(
        children: [
          Icon(
            stale ? Icons.warning_amber_rounded : Icons.check_circle_outline,
            size: 18,
            color: stale ? AppColors.warning : AppColors.success,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              when == null
                  ? context.t('You have never backed up. It takes one tap.')
                  : days == 0
                      ? context.t('Backed up today.')
                      : context.t('Last backed up ${Fmt.relative(when)}'
                          '${stale ? ' — worth doing again.' : '.'}'),
              style: theme.textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.busy,
    required this.onTap,
    this.danger = false,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final bool busy;
  final VoidCallback onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final tint = danger ? AppColors.danger : AppColors.primary;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: AppCard(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        onTap: busy ? null : onTap,
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: tint.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: busy
                  ? const Padding(
                      padding: EdgeInsets.all(11),
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Icon(icon, size: 20, color: tint),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: danger ? AppColors.danger : null,
                        ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, size: 18),
          ],
        ),
      ),
    );
  }
}
