import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/document_types.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';
import 'print_sheet.dart';

class InvoiceDetailScreen extends ConsumerWidget {
  const InvoiceDetailScreen({super.key, required this.voucherId});

  final String voucherId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(voucherProvider(voucherId));
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Invoice')),
        actions: [
          // valueOrNull, so Print / Share / Cancel do not disappear from the
          // app bar every time this invoice is refreshed — which happens after
          // recording a payment, i.e. exactly when someone wants to print.
          if (async.valueOrNull case final voucher?)
            PopupMenuButton<String>(
              onSelected: (action) => _onAction(context, ref, voucher, action),
              itemBuilder: (_) => [
                PopupMenuItem(
                  value: 'print',
                  child: ListTile(
                    dense: true,
                    leading: const Icon(Icons.print_outlined),
                    title: Text(context.t('Print receipt')),
                  ),
                ),
                PopupMenuItem(
                  value: 'whatsapp',
                  child: ListTile(
                    dense: true,
                    leading: const Icon(Icons.chat_outlined),
                    title: Text(context.t('Send on WhatsApp')),
                  ),
                ),
                PopupMenuItem(
                  value: 'share',
                  child: ListTile(
                    dense: true,
                    leading: const Icon(Icons.share_outlined),
                    title: Text(context.t('Share summary')),
                  ),
                ),
                // Built from what the server says this document may become, so
                // a conversion it would refuse never appears here at all.
                for (final target in voucher.convertibleTo)
                  PopupMenuItem(
                    value: 'convert:$target',
                    child: ListTile(
                      dense: true,
                      leading: Icon(DocumentType.of(target).icon),
                      title: Text(
                        context.t('Make into ${DocumentType.of(target).label.toLowerCase()}'),
                      ),
                    ),
                  ),
                // A wrong figure has to be fixable. Without this the only way
                // out of a typo was cancelling and typing the whole bill again
                // under a new number — which is a different bill as far as the
                // customer holding the old one is concerned.
                //
                // Not offered once it is cancelled or converted: there is
                // nothing live left to correct, and the document it became is
                // the one that counts.
                if (voucher.status != 'cancelled' && !voucher.isConverted)
                  PopupMenuItem(
                    value: 'edit',
                    child: ListTile(
                      dense: true,
                      leading: const Icon(Icons.edit_outlined),
                      title: Text(context.t('Edit')),
                    ),
                  ),
                if (voucher.status != 'cancelled' && !voucher.isConverted)
                  const PopupMenuItem(
                    value: 'cancel',
                    child: ListTile(
                      dense: true,
                      leading: Icon(Icons.block_outlined, color: AppColors.danger),
                      title: Text('Cancel invoice',
                          style: TextStyle(color: AppColors.danger)),
                    ),
                  ),
                PopupMenuItem(
                  value: 'delete',
                  child: ListTile(
                    dense: true,
                    leading: const Icon(Icons.delete_outline,
                        color: AppColors.danger),
                    title: Text(context.t('Delete'),
                        style: const TextStyle(color: AppColors.danger)),
                  ),
                ),
              ],
            ),
        ],
      ),
      // The saved copy, if there is one, beats a spinner over an invoice the
      // shopkeeper was already reading — recording a payment refreshes this
      // screen, and blanking it each time is what makes an app feel unsteady.
      body: switch (async) {
        AsyncValue(:final value?) => _Body(voucher: value, symbol: symbol),
        AsyncValue(:final error?) => EmptyState(
            title: context.t('Could not load this invoice'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(voucherProvider(voucherId)),
          ),
        _ => const Center(child: CircularProgressIndicator()),
      },
    );
  }

  Future<void> _onAction(
    BuildContext context,
    WidgetRef ref,
    Voucher voucher,
    String action,
  ) async {
    final symbol = ref.read(sessionProvider).symbol;
    final summary = '${voucher.typeLabel} ${voucher.number}\n'
        '${voucher.partyName ?? 'Walk-in'}\n'
        'Total: ${Fmt.money(voucher.total, symbol: symbol, decimals: false)}';

    if (action.startsWith('convert:')) {
      await _convert(context, ref, voucher, action.substring(8));
      return;
    }

    switch (action) {
      case 'edit':
        context.pushNamed(
          Routes.invoiceForm,
          queryParameters: {
            'type': voucher.voucherType,
            'edit': voucher.id,
          },
        );

      case 'delete':
        // Cancelling and deleting are different answers to different
        // questions. A bill that happened and was undone stays in the books,
        // marked cancelled, because the customer has a copy and the numbering
        // has to stay unbroken. A bill that never should have existed — a
        // duplicate, a test, a slip of the hand — is deleted, and saying so is
        // the only way to tell the shopkeeper which one they are choosing.
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(context.t('Delete ${voucher.number}?')),
            content: Text(
              context.t('It goes for good — no record that it existed. Stock '
                  'and the customer balance are put back.\n\nIf the bill really '
                  'happened and was returned, cancel it instead: that keeps it '
                  'in your records where the customer\'s copy can be matched '
                  'against it.'),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: Text(context.t('Keep it')),
              ),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: Text(context.t('Delete')),
              ),
            ],
          ),
        );
        if (confirmed != true || !context.mounted) return;
        try {
          await ref.read(voucherRepositoryProvider).delete(voucher.id);
          if (!context.mounted) return;
          invalidateBusinessData(ref);
          showSuccess(context, '${voucher.number} deleted.');
          context.pop();
        } catch (error) {
          if (context.mounted) showError(context, error);
        }

      case 'print':
        await showPrintSheet(context, voucher);

      case 'whatsapp':
        final phone = voucher.partyPhone?.replaceAll(RegExp(r'[^\d]'), '');
        if (phone == null || phone.isEmpty) {
          showError(context, 'This customer has no phone number saved.');
          return;
        }
        final uri = Uri.parse('https://wa.me/$phone?text=${Uri.encodeComponent(summary)}');
        if (await canLaunchUrl(uri)) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        }

      case 'share':
        await Share.share(summary, subject: '${voucher.typeLabel} ${voucher.number}');

      case 'cancel':
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(context.t('Cancel this invoice?')),
            content: const Text(
              'Stock and the customer balance are restored. The invoice stays '
              'in your records, marked cancelled.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: Text(context.t('Keep it')),
              ),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: Text(context.t('Cancel invoice')),
              ),
            ],
          ),
        );
        if (confirmed != true || !context.mounted) return;
        try {
          await ref.read(voucherRepositoryProvider).cancel(voucher.id, 'Cancelled by user');
          if (!context.mounted) return;
          ref.invalidate(voucherProvider(voucher.id));
          invalidateBusinessData(ref);
          showSuccess(context, 'Invoice cancelled.');
        } catch (error) {
          if (context.mounted) showError(context, error);
        }
    }
  }

  /// Turns a promise into the transaction it was always going to become.
  ///
  /// The original is kept and marked converted rather than replaced: a customer
  /// who signed off on an order will ask to see that order, and a shop that
  /// cannot produce it has lost the argument.
  Future<void> _convert(
    BuildContext context,
    WidgetRef ref,
    Voucher voucher,
    String target,
  ) async {
    final doc = DocumentType.of(target);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('Make into ${doc.label.toLowerCase()}?')),
        content: Text(
          context.t('${voucher.number} stays in your records, marked converted. '
              'A new ${doc.label.toLowerCase()} is created with the same items '
              'and rates'
              '${doc.movesStock ? ', and stock moves.' : '.'}'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(context.t('Not yet')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(context.t('Yes, create it')),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    try {
      final created =
          await ref.read(voucherRepositoryProvider).convert(voucher.id, target);
      if (!context.mounted) return;

      ref.invalidate(voucherProvider(voucher.id));
      invalidateBusinessData(ref);
      showSuccess(context, '${created.number} created.');
      context.pushReplacementNamed(
        Routes.invoiceDetail,
        pathParameters: {'id': created.id},
      );
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.voucher, required this.symbol});

  final Voucher voucher;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        AppCard(
          child: Column(
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          voucher.number,
                          style: theme.textTheme.titleLarge
                              ?.copyWith(fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '${voucher.typeLabel} · ${Fmt.date(voucher.voucherDate)}',
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                        ),
                      ],
                    ),
                  ),
                  StatusChip(voucher.isOverdue ? 'overdue' : voucher.status),
                ],
              ),
              const Divider(height: 24),
              Row(
                children: [
                  if (voucher.partyName != null) ...[
                    NameAvatar(voucher.partyName!, size: 38),
                    const SizedBox(width: 10),
                  ],
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          voucher.partyName ?? 'Walk-in customer',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        if (voucher.partyPhone != null)
                          Text(
                            voucher.partyPhone!,
                            style: theme.textTheme.bodySmall,
                          ),
                      ],
                    ),
                  ),
                  if (voucher.partyId != null)
                    TextButton(
                      onPressed: () => context.goNamed(
                        Routes.partyDetail,
                        pathParameters: {'id': voucher.partyId!},
                      ),
                      child: Text(context.t('View')),
                    ),
                ],
              ),
            ],
          ),
        ),

        if (voucher.fromAi) ...[
          const SizedBox(height: 10),
          Builder(builder: (context) {
            // primarySurface is a near-white wash and primaryDarker is a deep
            // orange: fine together on a white page, but on a dark one this
            // became a glaring pale block. The tint pair adapts to both.
            final brightness = Theme.of(context).brightness;
            final tint = AppColors.softTint(AppColors.primary, brightness);
            final onTint = AppColors.onSoftTint(AppColors.primary, brightness);

            return AppCard(
              color: tint,
              borderColor: tint,
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Icon(Icons.auto_awesome, size: 16, color: onTint),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      context.t(
                        voucher.source == 'ocr'
                            ? 'Created from a scanned bill'
                            : 'Created by the assistant',
                      ),
                      style: TextStyle(
                        fontSize: 12,
                        color: onTint,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            );
          }),
        ],

        const SizedBox(height: 16),
        Text('Items', style: theme.textTheme.titleMedium),
        const SizedBox(height: 8),
        AppCard(
          padding: EdgeInsets.zero,
          child: Column(
            children: [
              for (final (index, line) in voucher.lines.indexed) ...[
                if (index > 0) const Divider(height: 1),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              line.itemName,
                              style: const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              '${Fmt.qty(line.qty)} ${line.unitLabel} × '
                              '${Fmt.money(line.rate, symbol: symbol, decimals: false)}'
                              '${line.taxRate > 0 ? '  ·  ${Fmt.qty(line.taxRate)}% tax' : ''}',
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                            ),
                          ],
                        ),
                      ),
                      MoneyText(
                        line.total,
                        symbol: symbol,
                        decimals: false,
                        style: theme.textTheme.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),

        const SizedBox(height: 14),
        AppCard(
          child: Column(
            children: [
              _row(context, 'Subtotal', voucher.subtotal),
              if (voucher.discountAmount > 0)
                _row(context, 'Discount', -voucher.discountAmount),
              if (voucher.taxAmount > 0) _row(context, 'Tax', voucher.taxAmount),
              const Divider(height: 20),
              _row(context, 'Total', voucher.total, emphasise: true),
              if (voucher.paidAmount > 0) ...[
                const SizedBox(height: 4),
                _row(context, 'Paid', voucher.paidAmount, color: AppColors.success),
                _row(
                  context,
                  'Balance due',
                  voucher.balanceAmount,
                  color: voucher.balanceAmount > 0 ? AppColors.danger : AppColors.success,
                  emphasise: true,
                ),
              ],
            ],
          ),
        ),

        if (voucher.notes != null && voucher.notes!.isNotEmpty) ...[
          const SizedBox(height: 14),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Notes', style: theme.textTheme.labelLarge),
                const SizedBox(height: 4),
                Text(voucher.notes!),
              ],
            ),
          ),
        ],

        if (!voucher.isPaid && voucher.status != 'cancelled' && voucher.partyId != null) ...[
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: () => _collect(context, ref),
            icon: const Icon(Icons.payments_outlined, size: 20),
            label: Text(
              'Collect ${Fmt.money(voucher.balanceAmount, symbol: symbol, decimals: false)}',
            ),
          ),
        ],
      ],
    );
  }

  Widget _row(
    BuildContext context,
    String label,
    num value, {
    bool emphasise = false,
    Color? color,
  }) {
    final theme = Theme.of(context);
    final style = emphasise
        ? theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800, color: color)
        : theme.textTheme.bodyMedium?.copyWith(color: color);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: style),
          MoneyText(value, symbol: symbol, style: style),
        ],
      ),
    );
  }

  Future<void> _collect(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(paymentRepositoryProvider).settle(
            partyId: voucher.partyId!,
            amount: voucher.balanceAmount,
            direction: voucher.isSale ? 'in' : 'out',
          );
      if (!context.mounted) return;
      ref.invalidate(voucherProvider(voucher.id));
      invalidateBusinessData(ref);
      showSuccess(context, 'Payment recorded.');
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }
}
