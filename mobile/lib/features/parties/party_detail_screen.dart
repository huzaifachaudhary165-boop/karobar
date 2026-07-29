import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// One party: balance, actions, and the running ledger.
class PartyDetailScreen extends ConsumerWidget {
  const PartyDetailScreen({super.key, required this.partyId});

  final String partyId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(partyProvider(partyId));
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Party')),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit_outlined),
            onPressed: () => context.goNamed(
              Routes.partyForm,
              queryParameters: {'id': partyId},
            ),
          ),
        ],
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => EmptyState(
          title: 'Could not load this party',
          message: error.toString(),
          isError: true,
          actionLabel: 'Retry',
          onAction: () => ref.invalidate(partyProvider(partyId)),
        ),
        data: (party) => RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(partyProvider(partyId));
            ref.invalidate(partyLedgerProvider(partyId));
          },
          child: ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              _Header(party: party, symbol: symbol),
              _Actions(party: party),
              const SectionHeader('Statement'),
              _Ledger(partyId: partyId, symbol: symbol),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.party, required this.symbol});

  final Party party;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: AppCard(
        child: Column(
          children: [
            Row(
              children: [
                NameAvatar(party.name, size: 54),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        party.name,
                        style: theme.textTheme.titleLarge
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        [
                          Fmt.titleCase(party.partyType),
                          if (party.phone != null) party.phone!,
                        ].join(' · '),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const Divider(height: 28),
            Row(
              children: [
                Expanded(
                  child: Column(
                    children: [
                      Text(
                        party.balance == 0
                            ? 'Settled'
                            : party.owesUs
                                ? 'Owes you'
                                : 'You owe',
                        style: theme.textTheme.labelMedium
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                      const SizedBox(height: 4),
                      MoneyText(
                        party.balance.abs(),
                        symbol: symbol,
                        style: theme.textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w800,
                          color: AppColors.forBalance(party.balance, dark: isDark),
                        ),
                      ),
                    ],
                  ),
                ),
                Container(width: 1, height: 40, color: theme.colorScheme.outlineVariant),
                Expanded(
                  child: Column(
                    children: [
                      Text(
                        'Total business',
                        style: theme.textTheme.labelMedium
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                      const SizedBox(height: 4),
                      MoneyText(
                        party.totalSales,
                        symbol: symbol,
                        compact: true,
                        style: theme.textTheme.titleLarge
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                      Text(
                        '${party.transactionCount} transactions',
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            if (party.isOverCreditLimit) ...[
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppColors.softTint(AppColors.warning, Theme.of(context).brightness),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.warning_amber_rounded,
                        size: 16, color: AppColors.warning),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Over the credit limit of '
                        '${Fmt.money(party.creditLimit, symbol: symbol, decimals: false)}',
                        style: const TextStyle(
                          color: AppColors.warning,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Actions extends ConsumerWidget {
  const _Actions({required this.party});

  final Party party;

  Future<void> _settle(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController(text: party.balance.abs().toStringAsFixed(0));
    final symbol = ref.read(sessionProvider).symbol;

    final amount = await showModalBottomSheet<num>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 20,
          bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              party.owesUs ? 'Receive payment' : 'Make payment',
              style: Theme.of(sheetContext).textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              'From ${party.name} · outstanding '
              '${Fmt.money(party.balance.abs(), symbol: symbol, decimals: false)}',
              style: Theme.of(sheetContext).textTheme.bodySmall,
            ),
            const SizedBox(height: 18),
            TextField(
              controller: controller,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: context.t('Amount'),
                prefixText: symbol,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Settles the oldest unpaid bills first.',
              style: Theme.of(sheetContext).textTheme.bodySmall,
            ),
            const SizedBox(height: 18),
            FilledButton(
              onPressed: () => Navigator.pop(
                sheetContext,
                num.tryParse(controller.text.trim()),
              ),
              child: Text(context.t('Record payment')),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );

    if (amount == null || amount <= 0 || !context.mounted) return;

    try {
      final result = await ref.read(paymentRepositoryProvider).settle(
            partyId: party.id,
            amount: amount,
            direction: party.owesUs ? 'in' : 'out',
          );
      if (!context.mounted) return;
      ref.invalidate(partyProvider(party.id));
      ref.invalidate(partyLedgerProvider(party.id));
      invalidateBusinessData(ref);

      final settled = (result['settled_vouchers'] as List?)?.length ?? 0;
      showSuccess(
        context,
        settled > 0
            ? 'Payment recorded against $settled bill(s).'
            : 'Payment recorded as an advance.',
      );
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  Future<void> _call(BuildContext context) async {
    final phone = party.phone;
    if (phone == null) return;
    final uri = Uri.parse('tel:$phone');
    if (await canLaunchUrl(uri)) await launchUrl(uri);
  }

  Future<void> _whatsapp(BuildContext context, WidgetRef ref) async {
    final phone = party.phone?.replaceAll(RegExp(r'[^\d]'), '');
    if (phone == null || phone.isEmpty) return;
    final symbol = ref.read(sessionProvider).symbol;
    final message = Uri.encodeComponent(
      'Assalam-o-alaikum ${party.name},\n\n'
      'Aap ka balance ${Fmt.money(party.balance.abs(), symbol: symbol, decimals: false)} hai. '
      'Baraye meherbani adaigi karein. Shukriya.',
    );
    final uri = Uri.parse('https://wa.me/$phone?text=$message');
    if (await canLaunchUrl(uri)) await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(
        children: [
          Expanded(
            child: ActionTile(
              icon: Icons.receipt_long,
              label: 'New bill',
              onTap: () => context.goNamed(
                Routes.invoiceForm,
                queryParameters: {
                  'type': party.isCustomer ? 'sale' : 'purchase',
                  'party': party.id,
                },
              ),
            ),
          ),
          Expanded(
            child: ActionTile(
              icon: Icons.payments_outlined,
              label: party.owesUs ? 'Receive' : 'Pay',
              color: AppColors.success,
              onTap: () => _settle(context, ref),
            ),
          ),
          if (party.phone != null) ...[
            Expanded(
              child: ActionTile(
                icon: Icons.chat_outlined,
                label: 'WhatsApp',
                color: const Color(0xFF25D366),
                onTap: () => _whatsapp(context, ref),
              ),
            ),
            Expanded(
              child: ActionTile(
                icon: Icons.call_outlined,
                label: 'Call',
                color: AppColors.info,
                onTap: () => _call(context),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Ledger extends ConsumerWidget {
  const _Ledger({required this.partyId, required this.symbol});

  final String partyId;
  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(partyLedgerProvider(partyId));

    return async.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(32),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Padding(
        padding: const EdgeInsets.all(16),
        child: Text('Could not load the statement: $error'),
      ),
      data: (entries) {
        if (entries.isEmpty) {
          return Padding(
            padding: const EdgeInsets.all(32),
            child: Center(child: Text(context.t('No transactions yet.'))),
          );
        }
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: AppCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: [
                for (final (index, entry) in entries.reversed.indexed) ...[
                  if (index > 0) const Divider(height: 1),
                  ListTile(
                    dense: true,
                    title: Text(
                      entry.description,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
                    ),
                    subtitle: Text(
                      Fmt.date(entry.date),
                      style: const TextStyle(fontSize: 11),
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          entry.debit > 0
                              ? '+${Fmt.money(entry.debit, symbol: symbol, decimals: false)}'
                              : '-${Fmt.money(entry.credit, symbol: symbol, decimals: false)}',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: entry.debit > 0 ? AppColors.danger : AppColors.success,
                          ),
                        ),
                        Text(
                          Fmt.money(entry.balance, symbol: symbol, decimals: false),
                          style: const TextStyle(fontSize: 10.5),
                        ),
                      ],
                    ),
                    onTap: entry.referenceId != null && entry.entryType.contains('sale')
                        ? () => context.goNamed(
                              Routes.invoiceDetail,
                              pathParameters: {'id': entry.referenceId!},
                            )
                        : null,
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
