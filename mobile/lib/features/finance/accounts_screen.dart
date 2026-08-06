import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Cash drawers, bank accounts and wallets, and money moved between them.
///
/// Banking the day's takings is not income — it is the same money in a
/// different place — so it lives here rather than anywhere near profit.
class AccountsScreen extends ConsumerWidget {
  const AccountsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accounts = ref.watch(bankAccountsProvider);
    final transfers = ref.watch(transfersProvider);
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Cash & bank'))),
      floatingActionButton: accounts.maybeWhen(
        data: (rows) => rows.length >= 2
            ? FloatingActionButton.extended(
                onPressed: () => _transfer(context, ref, rows),
                icon: const Icon(Icons.swap_horiz),
                label: Text(context.t('Transfer')),
              )
            : null,
        orElse: () => null,
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(bankAccountsProvider);
          ref.invalidate(transfersProvider);
        },
        child: accounts.when(
          loading: () => const ListSkeleton(),
          error: (error, _) => EmptyState(
            title: context.t('Could not load accounts'),
            message: error.toString(),
            isError: true,
            actionLabel: context.t('Retry'),
            onAction: () => ref.invalidate(bankAccountsProvider),
          ),
          data: (rows) => rows.isEmpty
              ? EmptyState(
                  title: context.t('No accounts yet'),
                  message: context.t(
                      'Add your cash drawer and your bank account so every payment '
                      'lands somewhere you can reconcile.'),
                  icon: Icons.account_balance_outlined,
                  actionLabel: context.t('Add an account'),
                  onAction: () => _addAccount(context, ref),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
                  children: [
                    _Totals(accounts: rows, symbol: symbol),
                    const SizedBox(height: 6),
                    for (final account in rows)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _AccountCard(account: account, symbol: symbol),
                      ),
                    OutlinedButton.icon(
                      onPressed: () => _addAccount(context, ref),
                      icon: const Icon(Icons.add),
                      label: Text(context.t('Add an account')),
                    ),
                    transfers.maybeWhen(
                      data: (moves) => moves.isEmpty
                          ? const SizedBox.shrink()
                          : Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                SectionHeader(context.t('Recent transfers')),
                                for (final move in moves.take(15))
                                  Padding(
                                    padding: const EdgeInsets.only(bottom: 8),
                                    child: _TransferRow(
                                      transfer: move,
                                      symbol: symbol,
                                    ),
                                  ),
                              ],
                            ),
                      orElse: () => const SizedBox.shrink(),
                    ),
                  ],
                ),
        ),
      ),
    );
  }

  Future<void> _addAccount(BuildContext context, WidgetRef ref) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _AccountForm(),
    );
    if (saved == true) ref.invalidate(bankAccountsProvider);
  }

  Future<void> _transfer(
    BuildContext context,
    WidgetRef ref,
    List<BankAccount> accounts,
  ) async {
    final moved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _TransferForm(accounts: accounts),
    );
    if (moved == true) {
      ref.invalidate(bankAccountsProvider);
      ref.invalidate(transfersProvider);
    }
  }
}

class _Totals extends StatelessWidget {
  const _Totals({required this.accounts, required this.symbol});

  final List<BankAccount> accounts;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final cash = accounts.where((a) => a.isCash).fold<num>(0, (s, a) => s + a.balance);
    final bank = accounts.where((a) => !a.isCash).fold<num>(0, (s, a) => s + a.balance);

    return Row(
      children: [
        Expanded(
          child: StatTile(
            label: context.t('In hand'),
            value: Fmt.money(cash, symbol: symbol, decimals: false),
            icon: Icons.payments_outlined,
            accent: AppColors.success,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: StatTile(
            label: context.t('In bank'),
            value: Fmt.money(bank, symbol: symbol, decimals: false),
            icon: Icons.account_balance_outlined,
          ),
        ),
      ],
    );
  }
}

class _AccountCard extends StatelessWidget {
  const _AccountCard({required this.account, required this.symbol});

  final BankAccount account;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final icon = switch (account.accountType) {
      'cash' => Icons.payments_outlined,
      'wallet' => Icons.smartphone_outlined,
      'credit_card' => Icons.credit_card,
      _ => Icons.account_balance_outlined,
    };

    final subtitle = [
      if (account.bankName != null && account.bankName!.isNotEmpty) account.bankName!,
      if (account.accountNumber != null && account.accountNumber!.isNotEmpty)
        // Only the tail: nobody needs a full account number on a list screen,
        // and a screenshot of this gets shared.
        '••••${account.accountNumber!.length > 4 ? account.accountNumber!.substring(account.accountNumber!.length - 4) : account.accountNumber!}',
    ].join('  ·  ');

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: AppColors.primary.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, size: 19, color: AppColors.primary),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        account.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (account.isDefault) ...[
                      const SizedBox(width: 6),
                      const StatusChip('paid', label: 'Default', dense: true),
                    ],
                  ],
                ),
                if (subtitle.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
              ],
            ),
          ),
          MoneyText(
            account.balance,
            symbol: symbol,
            decimals: false,
            signed: true,
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}

class _TransferRow extends StatelessWidget {
  const _TransferRow({required this.transfer, required this.symbol});

  final AccountTransfer transfer;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          const Icon(Icons.swap_horiz, size: 18),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '${transfer.fromAccountName ?? '—'} → ${transfer.toAccountName ?? '—'}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
                Text(
                  Fmt.relative(transfer.transferDate) +
                      (transfer.charges > 0
                          ? '  ·  ${context.t('fee')} ${Fmt.money(transfer.charges, symbol: symbol, decimals: false)}'
                          : ''),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          Text(
            Fmt.money(transfer.amount, symbol: symbol, decimals: false),
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}

class _AccountForm extends ConsumerStatefulWidget {
  const _AccountForm();

  @override
  ConsumerState<_AccountForm> createState() => _AccountFormState();
}

class _AccountFormState extends ConsumerState<_AccountForm> {
  final _name = TextEditingController();
  final _bank = TextEditingController();
  final _number = TextEditingController();
  final _opening = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  String _type = 'cash';
  bool _saving = false;

  static const _types = {
    'cash': 'Cash drawer',
    'bank': 'Bank account',
    'wallet': 'Mobile wallet',
    'credit_card': 'Credit card',
  };

  @override
  void dispose() {
    _name.dispose();
    _bank.dispose();
    _number.dispose();
    _opening.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isBank = _type == 'bank';

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                context.t('New account'),
                style: Theme.of(context)
                    .textTheme
                    .titleLarge
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                initialValue: _type,
                decoration: InputDecoration(labelText: context.t('Type')),
                items: [
                  for (final entry in _types.entries)
                    DropdownMenuItem(value: entry.key, child: Text(context.t(entry.value))),
                ],
                onChanged: (value) => setState(() => _type = value ?? 'cash'),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                decoration: InputDecoration(
                  labelText: context.t('Name'),
                  hintText: context.t('Counter cash, Meezan current'),
                ),
                validator: (value) =>
                    (value ?? '').trim().isEmpty ? context.t('Give it a name') : null,
              ),
              if (isBank) ...[
                const SizedBox(height: 12),
                TextFormField(
                  controller: _bank,
                  textCapitalization: TextCapitalization.words,
                  decoration: InputDecoration(labelText: context.t('Bank')),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _number,
                  decoration: InputDecoration(labelText: context.t('Account number')),
                ),
              ],
              const SizedBox(height: 12),
              TextFormField(
                controller: _opening,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('Opening balance'),
                  hintText: context.t('What is in it today'),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Save')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);
    try {
      await ref.read(paymentRepositoryProvider).createAccount({
        'name': _name.text.trim(),
        'account_type': _type,
        if (_bank.text.trim().isNotEmpty) 'bank_name': _bank.text.trim(),
        if (_number.text.trim().isNotEmpty) 'account_number': _number.text.trim(),
        'opening_balance': num.tryParse(_opening.text.trim()) ?? 0,
      });
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}

class _TransferForm extends ConsumerStatefulWidget {
  const _TransferForm({required this.accounts});

  final List<BankAccount> accounts;

  @override
  ConsumerState<_TransferForm> createState() => _TransferFormState();
}

class _TransferFormState extends ConsumerState<_TransferForm> {
  final _amount = TextEditingController();
  final _charges = TextEditingController();
  final _reference = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  String? _fromId;
  String? _toId;
  bool _saving = false;

  @override
  void dispose() {
    _amount.dispose();
    _charges.dispose();
    _reference.dispose();
    super.dispose();
  }

  BankAccount? get _from =>
      widget.accounts.where((a) => a.id == _fromId).firstOrNull;

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;
    final theme = Theme.of(context);

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                context.t('Move money'),
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 4),
              Text(
                context.t('Between your own accounts. This is not income or expense.'),
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                initialValue: _fromId,
                decoration: InputDecoration(labelText: context.t('From')),
                items: [
                  for (final account in widget.accounts)
                    DropdownMenuItem(
                      value: account.id,
                      child: Text(
                        '${account.name}  ·  '
                        '${Fmt.money(account.balance, symbol: symbol, decimals: false)}',
                      ),
                    ),
                ],
                onChanged: (value) => setState(() {
                  _fromId = value;
                  if (_toId == value) _toId = null;
                }),
                validator: (value) =>
                    value == null ? context.t('Choose the sending account') : null,
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _toId,
                decoration: InputDecoration(labelText: context.t('To')),
                items: [
                  for (final account in widget.accounts.where((a) => a.id != _fromId))
                    DropdownMenuItem(value: account.id, child: Text(account.name)),
                ],
                onChanged: (value) => setState(() => _toId = value),
                validator: (value) =>
                    value == null ? context.t('Choose the receiving account') : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _amount,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(labelText: context.t('Amount')),
                validator: _validateAmount,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _charges,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: context.t('Bank charges'),
                  hintText: context.t('Leave empty if none'),
                  helperText: context.t('Taken from the sending account on top of the amount'),
                ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _reference,
                decoration: InputDecoration(
                  labelText: context.t('Reference'),
                  hintText: context.t('Cheque or transaction number'),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(context.t('Transfer')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String? _validateAmount(String? raw) {
    final value = num.tryParse((raw ?? '').trim());
    if (value == null || value <= 0) return context.t('Enter an amount');

    // A cash drawer cannot go negative in reality, so warn before the server
    // has to. Bank accounts can be overdrawn, so they are left alone.
    final source = _from;
    final fee = num.tryParse(_charges.text.trim()) ?? 0;
    if (source != null && source.isCash && value + fee > source.balance) {
      return context.t('${source.name} only has '
          '${Fmt.money(source.balance, decimals: false)}');
    }
    return null;
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);
    try {
      await ref.read(financeRepositoryProvider).transfer(
            fromAccountId: _fromId!,
            toAccountId: _toId!,
            amount: num.parse(_amount.text.trim()),
            charges: num.tryParse(_charges.text.trim()) ?? 0,
            referenceNumber: _reference.text.trim(),
          );
      if (mounted) {
        Navigator.pop(context, true);
        showSuccess(context, context.t('Money moved'));
      }
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}
