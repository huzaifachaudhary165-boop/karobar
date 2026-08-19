import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/network/api_exception.dart';
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

  /// Deletes the bill, and offers the way through when money is on it.
  ///
  /// A bill with a payment against it is refused, and rightly — the payment
  /// records cash that genuinely changed hands. But the refusal used to end
  /// there, telling the shopkeeper to "remove the payments first" from a
  /// screen with no way to do that. Trying to delete anything simply produced
  /// warnings, over and over.
  ///
  /// The second attempt keeps the money and drops only its link to this bill,
  /// so it sits on the customer's account for the next one.
  Future<void> _remove(
    BuildContext context,
    WidgetRef ref,
    Voucher voucher, {
    String payments = 'block',
  }) async {
    try {
      await ref
          .read(voucherRepositoryProvider)
          .delete(voucher.id, payments: payments);
      if (!context.mounted) return;
      invalidateBusinessData(ref);
      showSuccess(context, '${voucher.number} deleted.');
      context.pop();
    } on ApiException catch (error) {
      if (!context.mounted) return;

      if (error.details['can_release_payments'] != true) {
        showError(context, error);
        return;
      }

      final paid = num.tryParse('${error.details['paid_amount']}') ?? 0;
      final who = '${error.details['party_name'] ?? 'the customer'}';

      final choice = await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(context.t('${Fmt.money(paid)} was received on this bill')),
          // Two genuinely different situations, described by what happened at
          // the counter rather than by what the app will do about it. A
          // shopkeeper knows which of these is true; they do not know what
          // "release the allocation" means.
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DeleteChoice(
                icon: Icons.account_balance_wallet_outlined,
                title: context.t('The bill was wrong, the money was real'),
                detail: context.t('The bill goes. ${Fmt.money(paid)} stays on '
                    '$who\'s account as an advance for their next bill.'),
                onTap: () => Navigator.pop(dialogContext, 'release'),
              ),
              const SizedBox(height: 8),
              _DeleteChoice(
                icon: Icons.delete_forever_outlined,
                danger: true,
                title: context.t('None of it happened'),
                detail: context.t('A duplicate, a test, the wrong shop. The '
                    'bill and the ${Fmt.money(paid)} receipt both go, and the '
                    'cash comes back out of your drawer.'),
                onTap: () => Navigator.pop(dialogContext, 'delete'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: Text(context.t('Keep the bill')),
            ),
          ],
        ),
      );
      if (choice == null || !context.mounted) return;

      await _remove(context, ref, voucher, payments: choice);
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
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
        await _remove(context, ref, voucher);

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

/// One of the two things that can be meant by deleting a paid bill.
///
/// Written as a tappable card rather than a button row because the difference
/// between them is the sentence underneath, and a shopkeeper has to read that
/// before choosing — not after.
/// What the shop made on this bill.
///
/// The server's figure, costed against the stock that actually went out —
/// which is why it appears only once the bill exists. Set apart from the
/// amounts charged, and never printed: it is the shop's business, and a number
/// sitting among the totals would eventually be read out to a customer.
class _ProfitCard extends StatelessWidget {
  const _ProfitCard({
    required this.profit,
    required this.total,
    required this.symbol,
  });

  final num profit;
  final num total;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final losing = profit < 0;
    final tint = losing ? AppColors.danger : AppColors.success;
    final percent = total <= 0 ? 0 : (profit / total) * 100;

    return AppCard(
      color: tint.withValues(alpha: 0.07),
      borderColor: tint.withValues(alpha: 0.3),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          Icon(losing ? Icons.trending_down : Icons.trending_up,
              size: 20, color: tint),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.t(losing ? 'Sold at a loss' : 'You made'),
                  style: theme.textTheme.bodySmall,
                ),
                Text(
                  Fmt.money(profit.abs(), symbol: symbol, decimals: false),
                  style: theme.textTheme.titleMedium
                      ?.copyWith(color: tint, fontWeight: FontWeight.w800),
                ),
              ],
            ),
          ),
          if (!losing && percent > 0)
            Text(
              '${percentText(percent)}%',
              style: theme.textTheme.titleSmall?.copyWith(color: tint),
            ),
        ],
      ),
    );
  }
}

class _DeleteChoice extends StatelessWidget {
  const _DeleteChoice({
    required this.icon,
    required this.title,
    required this.detail,
    required this.onTap,
    this.danger = false,
  });

  final IconData icon;
  final String title;
  final String detail;
  final VoidCallback onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tint = danger ? AppColors.danger : AppColors.primary;

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      borderColor: tint.withValues(alpha: 0.4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: tint),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700, color: tint),
                ),
                const SizedBox(height: 2),
                Text(detail, style: theme.textTheme.bodySmall),
              ],
            ),
          ),
        ],
      ),
    );
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

        // What the shop actually made, once the bill exists and the server has
        // costed it against the stock that really went out. Kept off the
        // printed copy and out of the totals card: it is the shop's business,
        // not the customer's, and a figure sitting among the amounts charged
        // would eventually be read out to somebody.
        if (voucher.isSale && voucher.profit != 0) ...[
          const SizedBox(height: 14),
          _ProfitCard(profit: voucher.profit, total: voucher.total, symbol: symbol),
        ],

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
