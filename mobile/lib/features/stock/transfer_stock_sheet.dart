import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Move stock from one location to another.
///
/// The business-wide figure does not change here — this is about *where* the
/// goods are, not how many there are. The sheet shows what the source actually
/// holds before anything is typed, because "not enough stock" after the fact is
/// a worse answer than not offering the amount at all.
Future<void> showTransferStockSheet(
  BuildContext context,
  WidgetRef ref, {
  Item? item,
}) async {
  final moved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _TransferSheet(item: item),
  );
  if (moved == true) {
    ref.invalidate(godownsProvider);
    ref.invalidate(itemsProvider);
    if (item != null) ref.invalidate(itemGodownsProvider(item.id));
  }
}

class _TransferSheet extends ConsumerStatefulWidget {
  const _TransferSheet({this.item});

  final Item? item;

  @override
  ConsumerState<_TransferSheet> createState() => _TransferSheetState();
}

class _TransferSheetState extends ConsumerState<_TransferSheet> {
  final _qty = TextEditingController();
  final _note = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  Item? _item;
  String? _fromId;
  String? _toId;
  bool _saving = false;

  /// What the chosen source location holds of the chosen item. Null while it is
  /// still being fetched, so the field can say "checking" rather than "0".
  num? _available;

  @override
  void initState() {
    super.initState();
    _item = widget.item;
    if (_item != null) _refreshAvailable();
  }

  @override
  void dispose() {
    _qty.dispose();
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final godowns = ref.watch(godownsProvider).valueOrNull ?? const <Godown>[];
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
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              context.t('Transfer stock'),
              style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            Text(
              context.t('Moving goods between your own locations. '
                  'Your total stock does not change.'),
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 16),

            if (widget.item == null) ...[
              _ItemPicker(
                selected: _item,
                onSelected: (item) {
                  setState(() {
                    _item = item;
                    _available = null;
                  });
                  _refreshAvailable();
                },
              ),
              const SizedBox(height: 12),
            ] else
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AppCard(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  child: Row(
                    children: [
                      const Icon(Icons.inventory_2_outlined, size: 18),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          widget.item!.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.titleSmall
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  ),
                ),
              ),

            DropdownButtonFormField<String>(
              initialValue: _fromId,
              decoration: InputDecoration(labelText: context.t('From')),
              items: [
                for (final godown in godowns)
                  DropdownMenuItem(value: godown.id, child: Text(godown.name)),
              ],
              onChanged: (value) {
                setState(() {
                  _fromId = value;
                  _available = null;
                  if (_toId == value) _toId = null;
                });
                _refreshAvailable();
              },
              validator: (value) =>
                  value == null ? context.t('Choose where it is moving from') : null,
            ),
            if (_fromId != null && _item != null)
              Padding(
                padding: const EdgeInsets.only(top: 6, left: 4),
                child: Text(
                  _available == null
                      ? context.t('Checking what is there…')
                      : context.t('Available here: '
                          '${Fmt.qty(_available)} ${_item!.unitLabel}'),
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ),
            const SizedBox(height: 12),

            DropdownButtonFormField<String>(
              initialValue: _toId,
              decoration: InputDecoration(labelText: context.t('To')),
              items: [
                for (final godown in godowns.where((g) => g.id != _fromId))
                  DropdownMenuItem(value: godown.id, child: Text(godown.name)),
              ],
              onChanged: (value) => setState(() => _toId = value),
              validator: (value) =>
                  value == null ? context.t('Choose where it is going') : null,
            ),
            const SizedBox(height: 12),

            TextFormField(
              controller: _qty,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: context.t('Quantity'),
                suffixText: _item?.unitLabel,
              ),
              validator: _validateQty,
            ),
            const SizedBox(height: 12),

            TextFormField(
              controller: _note,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                labelText: context.t('Note'),
                hintText: context.t('Optional'),
              ),
            ),
            const SizedBox(height: 16),

            FilledButton(
              onPressed: _saving ? null : _submit,
              child: _saving
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(context.t('Transfer')),
            ),
          ],
        ),
      ),
    );
  }

  String? _validateQty(String? raw) {
    final value = num.tryParse((raw ?? '').trim());
    if (value == null || value <= 0) return context.t('Enter how much to move');
    // Checked here as well as on the server so the answer arrives while the
    // number is still on screen and can be corrected.
    if (_available != null && value > _available!) {
      return context.t('Only ${Fmt.qty(_available)} available there');
    }
    return null;
  }

  Future<void> _refreshAvailable() async {
    final item = _item;
    final from = _fromId;
    if (item == null || from == null) return;

    try {
      final rows = await ref.read(stockRepositoryProvider).whereItemIs(item.id);
      final match = rows.where((r) => r.godownId == from).firstOrNull;
      if (mounted && _item?.id == item.id && _fromId == from) {
        setState(() => _available = match?.qty ?? 0);
      }
    } catch (_) {
      // Not knowing is not a reason to block the transfer; the server still
      // refuses one that is too large.
      if (mounted) setState(() => _available = null);
    }
  }

  Future<void> _submit() async {
    if (_item == null) {
      showError(context, context.t('Choose an item first'));
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _saving = true);
    try {
      await ref.read(stockRepositoryProvider).transfer(
            itemId: _item!.id,
            fromGodownId: _fromId!,
            toGodownId: _toId!,
            qty: num.parse(_qty.text.trim()),
            note: _note.text.trim(),
          );
      if (mounted) {
        Navigator.pop(context, true);
        showSuccess(context, context.t('Stock moved'));
      }
    } catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showError(context, error);
      }
    }
  }
}

/// Type-ahead item search, so a shop with 2,000 lines is not a dropdown.
class _ItemPicker extends ConsumerStatefulWidget {
  const _ItemPicker({required this.selected, required this.onSelected});

  final Item? selected;
  final ValueChanged<Item> onSelected;

  @override
  ConsumerState<_ItemPicker> createState() => _ItemPickerState();
}

class _ItemPickerState extends ConsumerState<_ItemPicker> {
  final _controller = TextEditingController();
  List<Item> _results = const [];
  bool _searching = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: _controller,
          decoration: InputDecoration(
            labelText: context.t('Item'),
            hintText: context.t('Search by name, code or barcode'),
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _searching
                ? const Padding(
                    padding: EdgeInsets.all(12),
                    child: SizedBox(
                        width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                  )
                : null,
          ),
          onChanged: _search,
        ),
        if (_results.isNotEmpty)
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 180),
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final item in _results)
                  ListTile(
                    dense: true,
                    title: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text(item.stockLabel),
                    onTap: () {
                      _controller.text = item.name;
                      setState(() => _results = const []);
                      widget.onSelected(item);
                    },
                  ),
              ],
            ),
          ),
      ],
    );
  }

  Future<void> _search(String query) async {
    if (query.trim().length < 2) {
      setState(() => _results = const []);
      return;
    }
    setState(() => _searching = true);
    try {
      final found = await ref.read(itemRepositoryProvider).search(query);
      if (mounted) setState(() => _results = found);
    } catch (_) {
      if (mounted) setState(() => _results = const []);
    } finally {
      if (mounted) setState(() => _searching = false);
    }
  }
}
