import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/formatters.dart';
import '../../core/utils/screen.dart';
import '../../core/utils/trade_maths.dart';
import '../../core/widgets/calculator_sheet.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart' show trimZeros;
import '../../providers.dart';

/// Everything a wholesaler works out in a day, in one place.
///
/// A keypad is only the first of these and the least of them. The sums that
/// actually cost money are the ones with a formula somebody has to remember
/// the direction of: margin against markup, a chain of discounts, tax pulled
/// back out of a price that includes it, and a maund into kilos. Each is two
/// knowns and an answer, which is a form rather than a keypad — and doing them
/// on a phone calculator is where the mistakes live.
class CalculatorScreen extends ConsumerStatefulWidget {
  const CalculatorScreen({super.key});

  @override
  ConsumerState<CalculatorScreen> createState() => _CalculatorScreenState();
}

class _CalculatorScreenState extends ConsumerState<CalculatorScreen>
    with SingleTickerProviderStateMixin {
  late final _tabs = TabController(length: 5, vsync: this);

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Calculator')),
        bottom: TabBar(
          controller: _tabs,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: [
            Tab(text: context.t('Keypad')),
            Tab(text: context.t('Price & margin')),
            Tab(text: context.t('Discount')),
            Tab(text: context.t('Tax')),
            Tab(text: context.t('Units')),
          ],
        ),
      ),
      body: ReadableWidth(
        maxWidth: 720,
        padHorizontally: false,
        child: TabBarView(
          controller: _tabs,
          children: [
            const _KeypadTab(),
            _MarginTab(symbol: symbol),
            _DiscountTab(symbol: symbol),
            _TaxTab(symbol: symbol),
            const _UnitsTab(),
          ],
        ),
      ),
    );
  }
}

/// The plain one, for when the sum is just a sum.
class _KeypadTab extends StatelessWidget {
  const _KeypadTab();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.calculate_outlined,
                size: 46, color: AppColors.primary),
            const SizedBox(height: 12),
            Text(
              context.t('Add, multiply, take a percentage off — with every '
                  'step kept so you can check it.'),
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: () => showCalculator(context, title: 'Calculator'),
              icon: const Icon(Icons.grid_view_rounded, size: 18),
              label: Text(context.t('Open the keypad')),
            ),
          ],
        ),
      ),
    );
  }
}

/// A labelled number field that reports what was typed, as a number.
class _Field extends StatelessWidget {
  const _Field({
    required this.controller,
    required this.label,
    this.prefix,
    this.suffix,
    this.onChanged,
    this.autofocus = false,
  });

  final TextEditingController controller;
  final String label;
  final String? prefix;
  final String? suffix;
  final VoidCallback? onChanged;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      autofocus: autofocus,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      onChanged: (_) => onChanged?.call(),
      decoration: InputDecoration(
        labelText: context.t(label),
        prefixText: prefix,
        suffixText: suffix,
        isDense: true,
      ),
    );
  }
}

/// One answer, said plainly.
class _Answer extends StatelessWidget {
  const _Answer({
    required this.label,
    required this.value,
    this.hint,
    this.tint,
    this.big = false,
  });

  final String label;
  final String value;
  final String? hint;
  final Color? tint;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colour = tint ?? AppColors.primary;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(context.t(label), style: theme.textTheme.bodyMedium),
                if (hint != null)
                  Text(
                    context.t(hint!),
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            value,
            style: (big ? theme.textTheme.headlineSmall : theme.textTheme.titleMedium)
                ?.copyWith(fontWeight: FontWeight.w800, color: colour),
          ),
        ],
      ),
    );
  }
}

/// Cost, price and the two percentages people confuse.
class _MarginTab extends StatefulWidget {
  const _MarginTab({required this.symbol});

  final String symbol;

  @override
  State<_MarginTab> createState() => _MarginTabState();
}

class _MarginTabState extends State<_MarginTab> {
  final _cost = TextEditingController();
  final _price = TextEditingController();
  final _percent = TextEditingController();

  /// Which of the three the shopkeeper wants worked out.
  String _find = 'price';

  /// Whether the percentage they have in mind is of the cost or of the price.
  bool _asMargin = true;

  @override
  void dispose() {
    for (final c in [_cost, _price, _percent]) {
      c.dispose();
    }
    super.dispose();
  }

  num get _c => num.tryParse(_cost.text.trim()) ?? 0;
  num get _p => num.tryParse(_price.text.trim()) ?? 0;
  num get _pc => num.tryParse(_percent.text.trim()) ?? 0;

  @override
  Widget build(BuildContext context) {
    final symbol = widget.symbol;

    Widget answer() {
      if (_find == 'price') {
        if (_c <= 0 || _pc <= 0) return const SizedBox.shrink();
        final price = _asMargin
            ? Margin.priceForMargin(_c, _pc)
            : Margin.priceForMarkup(_c, _pc);
        if (price == null) {
          return const _Answer(
            label: 'Not possible',
            value: '—',
            tint: AppColors.danger,
            hint: 'A margin of 100% or more has no price. You probably mean '
                'markup — switch it above.',
          );
        }
        final m = Margin(cost: _c, price: price);
        return Column(
          children: [
            _Answer(
              label: 'Sell at',
              value: Fmt.money(price, symbol: symbol),
              big: true,
            ),
            const Divider(height: 20),
            _Answer(label: 'You make', value: Fmt.money(m.profit, symbol: symbol)),
            _Answer(
              label: 'Margin',
              hint: 'share of the selling price',
              value: '${trimZeros(m.marginPercent)}%',
            ),
            _Answer(
              label: 'Markup',
              hint: 'share of the cost',
              value: '${trimZeros(m.markupPercent)}%',
            ),
          ],
        );
      }

      if (_find == 'cost') {
        if (_p <= 0 || _pc <= 0) return const SizedBox.shrink();
        final cost = _asMargin
            ? Margin.costForMargin(_p, _pc)
            : _p / (1 + _pc / 100);
        if (cost == null) {
          return const _Answer(
            label: 'Not possible',
            value: '—',
            tint: AppColors.danger,
            hint: 'A margin of 100% or more cannot be worked back.',
          );
        }
        return _Answer(
          label: 'Buy at or under',
          value: Fmt.money(cost, symbol: symbol),
          big: true,
        );
      }

      if (_c <= 0 || _p <= 0) return const SizedBox.shrink();
      final m = Margin(cost: _c, price: _p);
      return Column(
        children: [
          _Answer(
            label: m.isLoss ? 'You lose' : 'You make',
            value: Fmt.money(m.profit.abs(), symbol: symbol),
            tint: m.isLoss ? AppColors.danger : AppColors.success,
            big: true,
          ),
          const Divider(height: 20),
          _Answer(
            label: 'Margin',
            hint: 'share of the selling price',
            value: '${trimZeros(m.marginPercent)}%',
            tint: m.isLoss ? AppColors.danger : null,
          ),
          _Answer(
            label: 'Markup',
            hint: 'share of the cost',
            value: '${trimZeros(m.markupPercent)}%',
            tint: m.isLoss ? AppColors.danger : null,
          ),
        ],
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SegmentedButton<String>(
          segments: [
            ButtonSegment(value: 'price', label: Text(context.t('Selling price'))),
            ButtonSegment(value: 'profit', label: Text(context.t('Profit'))),
            ButtonSegment(value: 'cost', label: Text(context.t('Buying price'))),
          ],
          selected: {_find},
          onSelectionChanged: (s) => setState(() => _find = s.first),
        ),
        const SizedBox(height: 6),
        Text(
          context.t('What do you want worked out?'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 14),

        if (_find != 'cost')
          _Field(
            controller: _cost,
            label: 'Cost price',
            prefix: symbol,
            autofocus: true,
            onChanged: () => setState(() {}),
          ),
        if (_find != 'cost') const SizedBox(height: 12),

        if (_find != 'price')
          _Field(
            controller: _price,
            label: 'Selling price',
            prefix: symbol,
            onChanged: () => setState(() {}),
          ),
        if (_find != 'price') const SizedBox(height: 12),

        if (_find != 'profit') ...[
          _Field(
            controller: _percent,
            label: _asMargin ? 'Margin you want' : 'Markup you want',
            suffix: '%',
            onChanged: () => setState(() {}),
          ),
          const SizedBox(height: 8),
          // The distinction that costs money, put where the number is typed.
          // Somebody quoted "20%" who reads it as markup sells at 120 instead
          // of 125 and is short on every unit.
          SegmentedButton<bool>(
            segments: [
              ButtonSegment(
                value: true,
                label: Text(context.t('of the selling price')),
              ),
              ButtonSegment(
                value: false,
                label: Text(context.t('on top of cost')),
              ),
            ],
            selected: {_asMargin},
            onSelectionChanged: (s) => setState(() => _asMargin = s.first),
          ),
        ],

        const SizedBox(height: 18),
        AppCard(child: answer()),
      ],
    );
  }
}

/// "Ten and five" — which is not fifteen.
class _DiscountTab extends StatefulWidget {
  const _DiscountTab({required this.symbol});

  final String symbol;

  @override
  State<_DiscountTab> createState() => _DiscountTabState();
}

class _DiscountTabState extends State<_DiscountTab> {
  final _amount = TextEditingController();
  final _discounts = <TextEditingController>[TextEditingController()];

  @override
  void dispose() {
    _amount.dispose();
    for (final c in _discounts) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final amount = num.tryParse(_amount.text.trim()) ?? 0;
    final percents = _discounts
        .map((c) => num.tryParse(c.text.trim()) ?? 0)
        .where((p) => p > 0)
        .toList();
    final d = Discount(amount, percents);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _Field(
          controller: _amount,
          label: 'Amount',
          prefix: widget.symbol,
          autofocus: true,
          onChanged: () => setState(() {}),
        ),
        const SizedBox(height: 14),
        Text(context.t('Discounts, one after another'),
            style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 2),
        Text(
          context.t('A supplier who says "10 and 5" means 10% off, then 5% off '
              'what is left. That is not 15%.'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 10),

        for (final (index, controller) in _discounts.indexed) ...[
          Row(
            children: [
              Expanded(
                child: _Field(
                  controller: controller,
                  label: index == 0 ? 'First discount' : 'Then',
                  suffix: '%',
                  onChanged: () => setState(() {}),
                ),
              ),
              if (_discounts.length > 1)
                IconButton(
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: () => setState(() {
                    _discounts.removeAt(index).dispose();
                  }),
                ),
            ],
          ),
          const SizedBox(height: 10),
        ],

        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () =>
                setState(() => _discounts.add(TextEditingController())),
            icon: const Icon(Icons.add, size: 18),
            label: Text(context.t('Another discount')),
          ),
        ),

        const SizedBox(height: 12),
        if (amount > 0 && percents.isNotEmpty)
          AppCard(
            child: Column(
              children: [
                _Answer(
                  label: 'Pay',
                  value: Fmt.money(d.finalAmount, symbol: widget.symbol),
                  big: true,
                ),
                const Divider(height: 20),
                _Answer(
                  label: 'Saved',
                  value: Fmt.money(d.saved, symbol: widget.symbol),
                  tint: AppColors.success,
                ),
                _Answer(
                  label: 'Which is really',
                  hint: 'the whole chain as one figure',
                  value: '${trimZeros(d.effectivePercent)}%',
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Tax on top, or dug back out of a price that already has it in.
class _TaxTab extends StatefulWidget {
  const _TaxTab({required this.symbol});

  final String symbol;

  @override
  State<_TaxTab> createState() => _TaxTabState();
}

class _TaxTabState extends State<_TaxTab> {
  final _amount = TextEditingController();
  final _rate = TextEditingController(text: '17');

  bool _inclusive = false;

  @override
  void dispose() {
    _amount.dispose();
    _rate.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final amount = num.tryParse(_amount.text.trim()) ?? 0;
    final rate = num.tryParse(_rate.text.trim()) ?? 0;
    final t = Tax(amount: amount, rate: rate, inclusive: _inclusive);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SegmentedButton<bool>(
          segments: [
            ButtonSegment(value: false, label: Text(context.t('Add tax'))),
            ButtonSegment(value: true, label: Text(context.t('Take tax out'))),
          ],
          selected: {_inclusive},
          onSelectionChanged: (s) => setState(() => _inclusive = s.first),
        ),
        const SizedBox(height: 6),
        Text(
          context.t(_inclusive
              ? 'The price already includes tax and you want the figure '
                  'underneath it.'
              : 'The price is before tax and you want the total.'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 14),

        _Field(
          controller: _amount,
          label: _inclusive ? 'Price including tax' : 'Price before tax',
          prefix: widget.symbol,
          autofocus: true,
          onChanged: () => setState(() {}),
        ),
        const SizedBox(height: 12),
        _Field(
          controller: _rate,
          label: 'Tax rate',
          suffix: '%',
          onChanged: () => setState(() {}),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final rate in ['0', '5', '16', '17', '18'])
              ChoiceChip(
                label: Text('$rate%'),
                selected: _rate.text.trim() == rate,
                showCheckmark: false,
                onSelected: (_) => setState(() => _rate.text = rate),
              ),
          ],
        ),

        const SizedBox(height: 18),
        if (amount > 0)
          AppCard(
            child: Column(
              children: [
                _Answer(
                  label: _inclusive ? 'Before tax' : 'Total with tax',
                  value: Fmt.money(_inclusive ? t.base : t.total,
                      symbol: widget.symbol),
                  big: true,
                ),
                const Divider(height: 20),
                _Answer(
                  label: 'Tax',
                  value: Fmt.money(t.tax, symbol: widget.symbol),
                ),
                _Answer(
                  label: _inclusive ? 'You were charged' : 'Before tax',
                  value: Fmt.money(_inclusive ? t.total : t.base,
                      symbol: widget.symbol),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Maund into kilos, thaan into gaz — the ones a general converter gets wrong.
class _UnitsTab extends StatefulWidget {
  const _UnitsTab();

  @override
  State<_UnitsTab> createState() => _UnitsTabState();
}

class _UnitsTabState extends State<_UnitsTab> {
  final _value = TextEditingController(text: '1');

  int _family = 0;
  late String _from = tradeUnits[0].units.keys.first;
  late String _to = tradeUnits[0].units.keys.elementAt(1);

  @override
  void dispose() {
    _value.dispose();
    super.dispose();
  }

  void _pickFamily(int index) {
    setState(() {
      _family = index;
      final keys = tradeUnits[index].units.keys.toList();
      _from = keys.first;
      _to = keys.length > 1 ? keys[1] : keys.first;
    });
  }

  @override
  Widget build(BuildContext context) {
    final family = tradeUnits[_family];
    final value = num.tryParse(_value.text.trim()) ?? 0;
    final result = family.convert(value, from: _from, to: _to);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final (index, f) in tradeUnits.indexed)
              ChoiceChip(
                label: Text(context.t(f.name)),
                selected: _family == index,
                showCheckmark: false,
                onSelected: (_) => _pickFamily(index),
              ),
          ],
        ),
        const SizedBox(height: 16),

        _Field(
          controller: _value,
          label: 'How much',
          onChanged: () => setState(() {}),
        ),
        const SizedBox(height: 12),

        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _from,
                isExpanded: true,
                decoration: InputDecoration(labelText: context.t('From')),
                items: [
                  for (final unit in family.units.keys)
                    DropdownMenuItem(
                      value: unit,
                      child: Text(unit, overflow: TextOverflow.ellipsis),
                    ),
                ],
                onChanged: (v) => setState(() => _from = v ?? _from),
              ),
            ),
            IconButton(
              icon: const Icon(Icons.swap_horiz),
              tooltip: context.t('Swap'),
              onPressed: () => setState(() {
                final was = _from;
                _from = _to;
                _to = was;
              }),
            ),
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _to,
                isExpanded: true,
                decoration: InputDecoration(labelText: context.t('To')),
                items: [
                  for (final unit in family.units.keys)
                    DropdownMenuItem(
                      value: unit,
                      child: Text(unit, overflow: TextOverflow.ellipsis),
                    ),
                ],
                onChanged: (v) => setState(() => _to = v ?? _to),
              ),
            ),
          ],
        ),

        const SizedBox(height: 18),
        AppCard(
          child: _Answer(
            label: '${trimZeros(value)} $_from',
            value: '${trimZeros(result)} $_to',
            big: true,
          ),
        ),

        const SizedBox(height: 10),
        Text(
          // Named, because a general converter gives the older Indian maund of
          // 37.32 kg and would be wrong by a tenth on every sack.
          context.t('A maund here is 40 kg, and forty seer make one — the '
              'figures a grain market quotes.'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}
