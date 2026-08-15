import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/utils/formatters.dart';
import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../data/offline_write.dart';
import '../../providers.dart';

/// Record an expense. Category is a free-typed chip list rather than a dropdown —
/// the backend creates a category on first use, so a shopkeeper never has to set
/// one up before recording a cost.
class ExpenseFormScreen extends ConsumerStatefulWidget {
  const ExpenseFormScreen({
    super.key,
    this.initialTitle,
    this.initialAmount,
    this.existing,
  });

  /// Filled in from a spoken command the phone understood without a signal —
  /// "bijli ka bill 3000". The shopkeeper reads it back and saves, rather than
  /// typing again what they just said.
  final String? initialTitle;
  final num? initialAmount;

  /// The expense being corrected.
  ///
  /// A mistyped amount could only be swiped away and re-entered, which loses
  /// the date it was actually paid and puts today's in its place.
  final Expense? existing;

  bool get isEditing => existing != null;

  @override
  ConsumerState<ExpenseFormScreen> createState() => _ExpenseFormScreenState();
}

class _ExpenseFormScreenState extends ConsumerState<ExpenseFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _amount = TextEditingController();
  final _vendor = TextEditingController();
  final _notes = TextEditingController();

  String? _category;
  DateTime _date = DateTime.now();
  String _paymentMode = 'cash';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    if (existing != null) {
      _title.text = existing.title;
      _amount.text = Fmt.qty(existing.amount);
      _vendor.text = existing.vendorName ?? '';
      _category = existing.categoryName;
      _date = existing.expenseDate;
      _paymentMode = existing.paymentMode;
      return;
    }

    if (widget.initialTitle != null) _title.text = widget.initialTitle!;
    if (widget.initialAmount != null) {
      _amount.text = widget.initialAmount!.toStringAsFixed(0);
    }
  }

  @override
  void dispose() {
    _title.dispose();
    _amount.dispose();
    _vendor.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);

    final body = <String, dynamic>{
      'title': _title.text.trim(),
      'amount': num.tryParse(_amount.text.trim()) ?? 0,
      'expense_date': Fmt.iso(_date),
      'payment_mode': _paymentMode,
      if (_category != null) 'category_name': _category,
      if (_vendor.text.trim().isNotEmpty) 'vendor_name': _vendor.text.trim(),
      if (_notes.text.trim().isNotEmpty) 'description': _notes.text.trim(),
    };

    try {
      // A correction goes straight to the server. The outbox replays a create,
      // so a queued edit would arrive as a second expense rather than a fix to
      // the first, and the shop would be shown paying its electricity twice.
      if (widget.isEditing) {
        await ref
            .read(expenseRepositoryProvider)
            .update(widget.existing!.id, body);
        if (!mounted) return;
        ref.invalidate(expensesProvider);
        ref.invalidate(expenseCategoriesProvider);
        invalidateBusinessData(ref);
        showSuccess(context, 'Expense updated.');
        context.pop();
        return;
      }

      final result = await saveOrQueue<void>(
        ref,
        entity: 'expense',
        data: body,
        send: () => ref.read(expenseRepositoryProvider).create(body),
      );
      if (!mounted) return;
      ref.invalidate(expensesProvider);
      ref.invalidate(expenseCategoriesProvider);
      invalidateBusinessData(ref);
      showSuccess(context, result.queued ? queuedMessage : 'Expense recorded.');
      context.pop();
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final symbol = ref.watch(sessionProvider).symbol;
    final categories = ref.watch(expenseCategoriesProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t(widget.isEditing ? 'Edit expense' : 'New expense')),
        actions: [
          TextButton(onPressed: _busy ? null : _save, child: Text(context.t('Save'))),
        ],
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            TextFormField(
              controller: _amount,
              autofocus: true,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800),
              decoration: InputDecoration(
                labelText: context.t('Amount *'),
                prefixText: symbol,
                prefixStyle: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
              ),
              validator: (value) {
                final parsed = num.tryParse(value?.trim() ?? '');
                return (parsed == null || parsed <= 0) ? 'Enter an amount' : null;
              },
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _title,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                labelText: context.t('What was it for? *'),
                hintText: 'Shop rent, staff salary, van fuel…',
                prefixIcon: const Icon(Icons.notes_outlined),
              ),
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? 'Describe the expense' : null,
            ),

            const SizedBox(height: 18),
            Text('Category', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            categories.when(
              loading: () => const LinearProgressIndicator(minHeight: 2),
              error: (_, __) => const SizedBox.shrink(),
              data: (rows) => Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final category in rows)
                    ChoiceChip(
                      label: Text(category.name),
                      selected: _category == category.name,
                      showCheckmark: false,
                      onSelected: (selected) => setState(
                        () => _category = selected ? category.name : null,
                      ),
                    ),
                ],
              ),
            ),

            const SizedBox(height: 18),
            AppCard(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              child: Row(
                children: [
                  const Icon(Icons.event_outlined, size: 19),
                  const SizedBox(width: 12),
                  Expanded(child: Text(Fmt.date(_date))),
                  TextButton(
                    onPressed: () async {
                      final picked = await showDatePicker(
                        context: context,
                        initialDate: _date,
                        firstDate: DateTime(2020),
                        lastDate: DateTime.now(),
                      );
                      if (picked != null) setState(() => _date = picked);
                    },
                    child: Text(context.t('Change')),
                  ),
                ],
              ),
            ),

            const SizedBox(height: 18),
            Text('Paid with', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                for (final mode in ['cash', 'bank', 'upi', 'cheque'])
                  ChoiceChip(
                    label: Text(Fmt.titleCase(mode)),
                    selected: _paymentMode == mode,
                    showCheckmark: false,
                    onSelected: (_) => setState(() => _paymentMode = mode),
                  ),
              ],
            ),

            const SizedBox(height: 18),
            TextFormField(
              controller: _vendor,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: context.t('Paid to (optional)'),
                prefixIcon: const Icon(Icons.storefront_outlined),
              ),
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _notes,
              maxLines: 2,
              decoration: InputDecoration(labelText: context.t('Notes (optional)')),
            ),

            const SizedBox(height: 26),
            FilledButton(
              onPressed: _busy ? null : _save,
              child: _busy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Text(context.t('Record expense')),
            ),
          ],
        ),
      ),
    );
  }
}
