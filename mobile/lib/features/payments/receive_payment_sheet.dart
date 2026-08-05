import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Records a payment, start to finish, without leaving the dashboard.
///
/// The Receive payment button used to navigate to the party list and stop
/// there. That is not what the button says it does: the shopkeeper has cash in
/// hand and a name in mind, and being shown a list is the app asking them to go
/// and find the feature themselves. Two taps and a number is the whole job.
///
/// Direction is decided per party rather than by the caller — "receive" and
/// "pay" are the same act seen from opposite sides of a balance, and a supplier
/// you owe should not need a different button.
Future<bool> showReceivePaymentSheet(BuildContext context, WidgetRef ref) async {
  final done = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => const _ReceivePaymentSheet(),
  );
  return done ?? false;
}

class _ReceivePaymentSheet extends ConsumerStatefulWidget {
  const _ReceivePaymentSheet();

  @override
  ConsumerState<_ReceivePaymentSheet> createState() => _SheetState();
}

class _SheetState extends ConsumerState<_ReceivePaymentSheet> {
  final _search = TextEditingController();
  final _amount = TextEditingController();

  Party? _party;
  bool _saving = false;
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    _amount.dispose();
    super.dispose();
  }

  void _choose(Party party) {
    setState(() {
      _party = party;
      // Pre-filled with what they owe, because that is the amount nine times
      // out of ten — and still editable for a part payment.
      _amount.text = party.outstanding > 0
          ? party.outstanding.toStringAsFixed(0)
          : '';
    });
  }

  Future<void> _save() async {
    final party = _party;
    final amount = num.tryParse(_amount.text.trim());
    if (party == null || amount == null || amount <= 0) return;

    setState(() => _saving = true);
    try {
      final result = await ref.read(paymentRepositoryProvider).settle(
            partyId: party.id,
            amount: amount,
            direction: party.owesUs ? 'in' : 'out',
          );
      if (!mounted) return;

      invalidateBusinessData(ref);
      ref.invalidate(paymentsProvider);

      final settled = (result['settled_vouchers'] as List?)?.length ?? 0;
      Navigator.of(context).pop(true);
      showSuccess(
        context,
        settled > 0
            ? '${context.t('Payment recorded against')} $settled ${context.t('bill(s).')}'
            : context.t('Payment recorded as an advance.'),
      );
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;
    final async = ref.watch(partiesProvider);

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
          child: _party == null
              ? _pickParty(theme, symbol, async)
              : _enterAmount(theme, symbol),
        ),
      ),
    );
  }

  Widget _pickParty(ThemeData theme, String symbol, AsyncValue<Paged<Party>> async) {
    final all = async.valueOrNull?.items ?? const <Party>[];
    // Anyone with a balance either way — a supplier you owe belongs here too.
    final owing = all.where((p) => p.outstanding > 0).toList()
      ..sort((a, b) => b.outstanding.compareTo(a.outstanding));
    final query = _query.trim().toLowerCase();
    final shown = (query.isEmpty ? owing : all)
        .where((p) => query.isEmpty || p.name.toLowerCase().contains(query))
        .take(40)
        .toList();

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          context.t('Who paid?'),
          style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _search,
          autofocus: false,
          onChanged: (value) => setState(() => _query = value),
          decoration: InputDecoration(
            hintText: context.t('Search by name'),
            prefixIcon: const Icon(Icons.search),
            isDense: true,
          ),
        ),
        const SizedBox(height: 8),
        if (async.isLoading && all.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 40),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (shown.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 34),
            child: Text(
              query.isEmpty
                  ? context.t('Nobody owes you anything right now. '
                      'Search to record a payment anyway.')
                  : context.t('No customer or supplier by that name.'),
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          )
        else
          ConstrainedBox(
            constraints: BoxConstraints(
              maxHeight: MediaQuery.of(context).size.height * 0.42,
            ),
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: shown.length,
              itemBuilder: (_, index) {
                final party = shown[index];
                final owes = party.owesUs;
                return ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: CircleAvatar(
                    radius: 18,
                    backgroundColor: AppColors.forName(party.name)
                        .withValues(alpha: 0.18),
                    child: Text(
                      party.name.characters.first.toUpperCase(),
                      style: TextStyle(
                        color: AppColors.forName(party.name),
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  title: Text(party.name),
                  subtitle: party.outstanding > 0
                      ? Text(owes
                          ? context.t('owes you')
                          : context.t('you owe them'))
                      : null,
                  trailing: party.outstanding > 0
                      ? Text(
                          Fmt.money(party.outstanding,
                              symbol: symbol, decimals: false),
                          style: TextStyle(
                            fontWeight: FontWeight.w800,
                            color: AppColors.forBalance(party.balance,
                                dark: theme.brightness == Brightness.dark),
                          ),
                        )
                      : null,
                  onTap: () => _choose(party),
                );
              },
            ),
          ),
      ],
    );
  }

  Widget _enterAmount(ThemeData theme, String symbol) {
    final party = _party!;
    final owes = party.owesUs;

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            IconButton(
              icon: const Icon(Icons.arrow_back),
              tooltip: context.t('Back'),
              onPressed: _saving ? null : () => setState(() => _party = null),
            ),
            Expanded(
              child: Text(
                owes
                    ? context.t('Receive payment')
                    : context.t('Make payment'),
                style: theme.textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
            ),
          ],
        ),
        const SizedBox(height: 2),
        Text(
          party.outstanding > 0
              ? '${party.name} · ${context.t('outstanding')} '
                  '${Fmt.money(party.outstanding, symbol: symbol, decimals: false)}'
              : party.name,
          style: theme.textTheme.bodySmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: _amount,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[\d.]'))],
          onChanged: (_) => setState(() {}),
          onSubmitted: (_) => _save(),
          style: theme.textTheme.headlineSmall
              ?.copyWith(fontWeight: FontWeight.w800),
          decoration: InputDecoration(
            labelText: context.t('Amount'),
            prefixText: '$symbol ',
          ),
        ),
        const SizedBox(height: 10),
        Text(
          context.t('Oldest bills are settled first. Anything left over is '
              'kept as an advance.'),
          style: theme.textTheme.bodySmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 18),
        FilledButton(
          onPressed: _saving || (num.tryParse(_amount.text.trim()) ?? 0) <= 0
              ? null
              : _save,
          child: _saving
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: Colors.white),
                )
              : Text(owes
                  ? context.t('Record payment received')
                  : context.t('Record payment made')),
        ),
      ],
    );
  }
}
