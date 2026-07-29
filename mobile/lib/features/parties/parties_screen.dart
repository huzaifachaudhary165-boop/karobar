import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/env.dart';
import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

class PartiesScreen extends ConsumerStatefulWidget {
  const PartiesScreen({super.key});

  @override
  ConsumerState<PartiesScreen> createState() => _PartiesScreenState();
}

class _PartiesScreenState extends ConsumerState<PartiesScreen> {
  final _controller = TextEditingController();
  Timer? _debounce;

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(Env.searchDebounce, () {
      ref.read(partySearchProvider.notifier).state = value.trim();
    });
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(partiesProvider);
    final filter = ref.watch(partyFilterProvider);
    final symbol = ref.watch(sessionProvider).symbol;
    final strings = context.s;

    return Scaffold(
      appBar: AppBar(
        title: Text(strings.get('parties')),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_add_outlined),
            tooltip: strings.get('add_customer'),
            onPressed: () => context.goNamed(Routes.partyForm),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: TextField(
              controller: _controller,
              onChanged: _onSearchChanged,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: context.t('Search by name or phone'),
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _controller.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _controller.clear();
                          ref.read(partySearchProvider.notifier).state = '';
                          setState(() {});
                        },
                      ),
              ),
            ),
          ),
          SizedBox(
            height: 46,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final entry in {
                  'all': 'All',
                  'customer': strings.get('customer'),
                  'supplier': strings.get('supplier'),
                  'receivable': strings.get('to_collect'),
                  'payable': strings.get('to_pay'),
                }.entries) ...[
                  ChoiceChip(
                    label: Text(entry.value),
                    selected: filter == entry.key,
                    showCheckmark: false,
                    onSelected: (_) =>
                        ref.read(partyFilterProvider.notifier).state = entry.key,
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          Expanded(
            child: async.when(
              loading: () => const ListSkeleton(),
              error: (error, _) => EmptyState(
                title: 'Could not load parties',
                message: error.toString(),
                isError: true,
                actionLabel: strings.get('retry'),
                onAction: () => ref.invalidate(partiesProvider),
              ),
              data: (page) => page.isEmpty
                  ? EmptyState(
                      title: strings.get('no_data'),
                      message: 'Add your first customer or supplier to start billing.',
                      icon: Icons.people_outline,
                      actionLabel: strings.get('add_customer'),
                      onAction: () => context.goNamed(Routes.partyForm),
                    )
                  : RefreshIndicator(
                      onRefresh: () async => ref.invalidate(partiesProvider),
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                        itemCount: page.items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (_, index) =>
                            _PartyRow(party: page.items[index], symbol: symbol),
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PartyRow extends StatelessWidget {
  const _PartyRow({required this.party, required this.symbol});

  final Party party;
  final String symbol;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final settled = party.balance == 0;

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () =>
          context.goNamed(Routes.partyDetail, pathParameters: {'id': party.id}),
      child: Row(
        children: [
          NameAvatar(party.name),
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
                        party.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (party.isOverCreditLimit) ...[
                      const SizedBox(width: 6),
                      const Icon(Icons.warning_amber_rounded,
                          size: 14, color: AppColors.warning),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  party.phone ??
                      (party.lastTransactionAt != null
                          ? Fmt.relative(party.lastTransactionAt)
                          : Fmt.titleCase(party.partyType)),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              MoneyText(
                party.balance.abs(),
                symbol: symbol,
                compact: true,
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: AppColors.forBalance(
                    party.balance,
                    dark: theme.brightness == Brightness.dark,
                  ),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                settled
                    ? context.tr('settled')
                    : party.owesUs
                        ? context.tr('owes_you')
                        : context.tr('you_owe'),
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
