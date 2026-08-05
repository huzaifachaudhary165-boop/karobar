import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/router/app_router.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/app_colors.dart';
import '../../core/utils/bill_reader.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Photograph a supplier bill and turn it into a draft purchase entry.
///
/// The reading happens here on the phone — Google ML Kit pulls the text out of
/// the photo offline and for free. Only that text goes to the server, which
/// structures it into a bill the shopkeeper reviews before anything is written.
class ScanScreen extends ConsumerStatefulWidget {
  const ScanScreen({super.key});

  @override
  ConsumerState<ScanScreen> createState() => _ScanScreenState();
}

enum _Stage { idle, reading, extracting, review, applied }

class _ScanScreenState extends ConsumerState<ScanScreen> {
  final _picker = ImagePicker();

  _Stage _stage = _Stage.idle;
  File? _image;
  OcrJob? _job;
  String? _error;
  String _target = 'purchase';

  Future<void> _pick(ImageSource source) async {
    // Scanning is four separate things — choose a photo, read it on the phone,
    // keep a copy, turn the text into a bill — and any of them can fail. They
    // all used to end at one catch that showed a single message, so "the
    // assistant hit a problem" was equally the answer for a cancelled picker,
    // an unreadable photo, a rejected upload and a refusal from the model. That
    // is not something anyone can act on, or report usefully.
    var step = 'choosing the photo';
    try {
      final picked = await _picker.pickImage(
        source: source,
        imageQuality: 92,
        // ML Kit reads the photo here on the phone, so resolution costs nothing
        // in upload time — only the extracted text is sent.
        maxWidth: 3000,
      );
      if (picked == null) return;

      setState(() {
        _image = File(picked.path);
        _stage = _Stage.reading;
        _error = null;
        _job = null;
      });

      // 1. Read the bill on-device. Free, offline, no quota.
      step = 'reading the photo on this phone';
      final bill = await BillReader.read(picked.path);
      if (!mounted) return;

      if (!bill.isUsable) {
        setState(() {
          _stage = _Stage.idle;
          _error = bill.problem;
        });
        return;
      }

      final repository = ref.read(aiRepositoryProvider);
      setState(() => _stage = _Stage.extracting);

      // 2. Keep the photo for the shopkeeper's records — best effort. A failed
      //    upload must not cost them the scan they already have text for.
      //
      //    But it must not be invisible either: this swallowed every failure,
      //    so when uploads were broken outright the bill still scanned and
      //    nobody could tell that no photo was ever being kept.
      step = 'saving a copy of the photo';
      String? attachmentId;
      String? attachmentProblem;
      try {
        attachmentId = await repository.uploadImage(
          await picked.readAsBytes(),
          picked.name,
        );
      } catch (error) {
        attachmentId = null;
        attachmentProblem = error.toString();
      }
      if (!mounted) return;
      if (attachmentProblem != null) {
        showError(
          context,
          '${context.t('The bill was read, but the photo could not be saved.')} '
          '$attachmentProblem',
        );
      }

      // 3. Turn that text into a draft bill.
      step = 'turning the text into a bill';
      final job = await repository.scan(bill.text, attachmentId: attachmentId);
      if (!mounted) return;

      setState(() {
        _job = job;
        _stage = job.isComplete ? _Stage.review : _Stage.idle;
        _error = job.error;
        _target = job.documentType == 'receipt' || job.documentType == 'expense'
            ? 'expense'
            : 'purchase';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.idle;
        _error = '${context.t('Failed while')} $step.\n\n$error';
      });
    }
  }

  @override
  void dispose() {
    // Releases the native ML Kit recogniser — it holds a model in memory.
    BillReader.dispose();
    super.dispose();
  }

  Future<void> _apply() async {
    if (_job == null) return;
    setState(() => _stage = _Stage.extracting);

    try {
      final job = await ref.read(aiRepositoryProvider).applyScan(_job!.id, target: _target);
      if (!mounted) return;
      invalidateBusinessData(ref);
      setState(() {
        _job = job;
        _stage = _Stage.applied;
      });

      final voucherId = job.createdVoucherId;
      if (voucherId != null) {
        showSuccess(context, 'Purchase bill created.');
        context.pushReplacementNamed(
          Routes.invoiceDetail,
          pathParameters: {'id': voucherId},
        );
      } else {
        showSuccess(context, 'Expense recorded.');
        context.pop();
      }
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.review;
        _error = error.toString();
      });
      showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('Scan a bill')),
        actions: [
          if (_job != null)
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: context.t('Start over'),
              onPressed: () => setState(() {
                _job = null;
                _image = null;
                _stage = _Stage.idle;
                _error = null;
              }),
            ),
        ],
      ),
      body: switch (_stage) {
        _Stage.idle => _Intro(error: _error, onPick: _pick),
        _Stage.reading => const _Progress(label: 'Reading the bill on your phone…'),
        _Stage.extracting => const _Progress(
            label: 'Making sense of it…',
            detail: 'Matching items and rates. Usually a few seconds.',
          ),
        _Stage.review || _Stage.applied => _Review(
            job: _job!,
            image: _image,
            target: _target,
            onTargetChanged: (value) => setState(() => _target = value),
            onApply: _apply,
          ),
      },
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro({required this.error, required this.onPick});

  final String? error;
  final void Function(ImageSource) onPick;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 20),
        Center(
          child: Container(
            width: 96,
            height: 96,
            decoration: BoxDecoration(
              color: AppColors.softTint(AppColors.primary, Theme.of(context).brightness),
              borderRadius: BorderRadius.circular(28),
            ),
            child: const Icon(
              Icons.document_scanner_outlined,
              size: 44,
              color: AppColors.primaryDarker,
            ),
          ),
        ),
        const SizedBox(height: 24),
        Text(
          'Photograph a supplier bill',
          textAlign: TextAlign.center,
          style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 8),
        Text(
          'The text is read on your phone — it works without internet and '
          'costs nothing. You review every figure before it is saved.',
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant, height: 1.5),
        ),
        if (error != null) ...[
          const SizedBox(height: 20),
          AppCard(
            color: AppColors.softTint(AppColors.danger, Theme.of(context).brightness),
            borderColor: AppColors.danger.withValues(alpha: 0.3),
            child: Row(
              children: [
                const Icon(Icons.error_outline, color: AppColors.danger, size: 18),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    error!,
                    style: const TextStyle(color: AppColors.danger, fontSize: 13),
                  ),
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 32),
        FilledButton.icon(
          onPressed: () => onPick(ImageSource.camera),
          icon: const Icon(Icons.camera_alt_outlined),
          label: const Text('Take a photo'),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () => onPick(ImageSource.gallery),
          icon: const Icon(Icons.photo_library_outlined),
          label: Text(context.t('Choose from gallery')),
        ),
        const SizedBox(height: 28),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('For the best results', style: theme.textTheme.titleSmall),
              const SizedBox(height: 10),
              for (final tip in const [
                'Lay the bill flat and fill the frame',
                'Make sure the light is even — avoid shadows',
                'Keep the totals row visible',
                'Handwritten bills work, but check the figures',
              ])
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.check, size: 15, color: AppColors.success),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(tip, style: theme.textTheme.bodySmall),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Progress extends StatelessWidget {
  const _Progress({required this.label, this.detail});

  final String label;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(width: 46, height: 46, child: CircularProgressIndicator()),
          const SizedBox(height: 22),
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          if (detail != null) ...[
            const SizedBox(height: 6),
            Text(
              detail!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Review extends ConsumerWidget {
  const _Review({
    required this.job,
    required this.image,
    required this.target,
    required this.onTargetChanged,
    required this.onApply,
  });

  final OcrJob job;
  final File? image;
  final String target;
  final ValueChanged<String> onTargetChanged;
  final VoidCallback onApply;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final symbol = ref.watch(sessionProvider).symbol;
    final data = job.extracted;
    final lines = (data['lines'] as List?) ?? const [];

    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (job.isLowConfidence)
                AppCard(
                  color: AppColors.softTint(AppColors.warning, Theme.of(context).brightness),
                  borderColor: AppColors.warning.withValues(alpha: 0.35),
                  child: Row(
                    children: [
                      const Icon(Icons.warning_amber_rounded,
                          color: AppColors.warning, size: 20),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Low confidence read — check every figure before saving.',
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: AppColors.warning, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                ),
              if (job.warnings.isNotEmpty) ...[
                const SizedBox(height: 10),
                for (final warning in job.warnings)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.info_outline, size: 14, color: AppColors.warning),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(warning, style: theme.textTheme.bodySmall),
                        ),
                      ],
                    ),
                  ),
              ],

              const SizedBox(height: 12),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                data['vendor_name']?.toString() ?? 'Unknown vendor',
                                style: theme.textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w700),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                [
                                  if (data['invoice_number'] != null)
                                    'Bill ${data['invoice_number']}',
                                  if (data['invoice_date'] != null)
                                    data['invoice_date'].toString(),
                                ].join(' · '),
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (job.confidence != null)
                          StatusChip(
                            job.isLowConfidence ? 'partial' : 'paid',
                            label: '${(job.confidence! * 100).round()}%',
                            dense: true,
                          ),
                      ],
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 16),
              Text('Items read (${lines.length})', style: theme.textTheme.titleMedium),
              const SizedBox(height: 8),
              if (lines.isEmpty)
                const AppCard(
                  child: Text('No line items could be read from this image.'),
                )
              else
                AppCard(
                  padding: EdgeInsets.zero,
                  child: Column(
                    children: [
                      for (final (index, raw) in lines.indexed) ...[
                        if (index > 0) const Divider(height: 1),
                        Builder(
                          builder: (_) {
                            final line = Map<String, dynamic>.from(raw as Map);
                            final qty = asNumOrNull(line['qty']) ?? 1;
                            final rate = asNum(line['rate']);
                            final amount = asNumOrNull(line['amount']) ?? qty * rate;
                            return Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 14,
                                vertical: 11,
                              ),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Text(
                                          line['name']?.toString() ?? '—',
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w600,
                                          ),
                                        ),
                                        Text(
                                          '${Fmt.qty(qty)} × '
                                          '${Fmt.money(rate, symbol: symbol, decimals: false)}',
                                          style: theme.textTheme.bodySmall?.copyWith(
                                            color: theme.colorScheme.onSurfaceVariant,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  MoneyText(
                                    amount,
                                    symbol: symbol,
                                    decimals: false,
                                    style: theme.textTheme.titleSmall,
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
                      ],
                    ],
                  ),
                ),

              const SizedBox(height: 14),
              AppCard(
                child: Column(
                  children: [
                    if (data['subtotal'] != null)
                      _row(context, 'Subtotal', asNum(data['subtotal']), symbol),
                    if (data['tax_amount'] != null)
                      _row(context, 'Tax', asNum(data['tax_amount']), symbol),
                    if (data['total'] != null) ...[
                      const Divider(height: 18),
                      _row(context, 'Total', asNum(data['total']), symbol, emphasise: true),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: 18),
              Text('Save as', style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: [
                  ButtonSegment(
                    value: 'purchase',
                    label: Text(context.t('Purchase bill')),
                    icon: const Icon(Icons.receipt_long_outlined),
                  ),
                  ButtonSegment(
                    value: 'expense',
                    label: Text(context.t('Expense')),
                    icon: const Icon(Icons.payments_outlined),
                  ),
                ],
                selected: {target},
                onSelectionChanged: (values) => onTargetChanged(values.first),
              ),

              if (image != null) ...[
                const SizedBox(height: 18),
                ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Image.file(image!, height: 200, fit: BoxFit.cover),
                ),
              ],
              const SizedBox(height: 90),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            border: Border(top: BorderSide(color: theme.colorScheme.outline)),
          ),
          child: SafeArea(
            top: false,
            child: FilledButton.icon(
              onPressed: job.isApplied ? null : onApply,
              icon: const Icon(Icons.check),
              label: Text(
                job.isApplied
                    ? 'Already saved'
                    : target == 'expense'
                        ? 'Save as expense'
                        : 'Create purchase bill',
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _row(
    BuildContext context,
    String label,
    num value,
    String symbol, {
    bool emphasise = false,
  }) {
    final theme = Theme.of(context);
    final style = emphasise
        ? theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)
        : theme.textTheme.bodyMedium;

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
}
