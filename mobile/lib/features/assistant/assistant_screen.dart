import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../../core/ai/offline_command.dart';
import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../data/models.dart';
import '../../providers.dart';
import '../expenses/expense_form_screen.dart';
import '../payments/receive_payment_sheet.dart';

/// Stands in for the error a request would have returned, when the phone
/// already knows there is nothing to send it to.
class _NoSignal {
  const _NoSignal();

  @override
  String toString() =>
      'No internet. Your work is saved here and goes up when the signal comes back.';
}

/// Something the phone understood with no signal, waiting for a tap.
///
/// Held rather than acted on. The shopkeeper reads back what was heard and
/// decides — an entry made silently from a misheard sentence is found weeks
/// later, in the wrong ledger.
class _OfflineOffer {
  const _OfflineOffer({required this.command, this.party});

  final OfflineCommand command;
  final Party? party;

  String get title => switch (command.intent) {
        CommandIntent.sale => 'Make a bill',
        CommandIntent.purchase => 'Record a purchase',
        CommandIntent.paymentIn => 'Money received',
        CommandIntent.paymentOut => 'Money paid',
        CommandIntent.expense => 'Record an expense',
        _ => 'Open',
      };

  IconData get icon => switch (command.intent) {
        CommandIntent.sale => Icons.receipt_long_outlined,
        CommandIntent.purchase => Icons.local_shipping_outlined,
        CommandIntent.paymentIn => Icons.south_west,
        CommandIntent.paymentOut => Icons.north_east,
        CommandIntent.expense => Icons.payments_outlined,
        _ => Icons.bolt_outlined,
      };

  /// What was actually understood, in the shopkeeper's own terms, so a
  /// mishearing is caught before it is saved rather than after.
  String detail(String symbol) {
    final parts = <String>[
      if (party != null)
        party!.name
      else if (command.nameHint != null)
        '${command.nameHint} — not in your list yet',
      if (command.qty != null)
        '${command.qty} ${command.unit ?? ''}'.trim(),
      if (command.amount != null)
        '$symbol${command.amount!.toStringAsFixed(0)}',
    ];
    return parts.isEmpty ? command.original : parts.join(' · ');
  }
}

/// The conversational surface: type or speak, and the assistant performs the
/// work through the same API the rest of the app uses.
///
/// Speech recognition runs on-device, so voice costs nothing and works on a
/// weak connection; only the transcript goes to the server.
class AssistantScreen extends ConsumerStatefulWidget {
  const AssistantScreen({super.key, this.initialPrompt});

  final String? initialPrompt;

  @override
  ConsumerState<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends ConsumerState<AssistantScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _speech = SpeechToText();

  final List<ChatMessage> _messages = [];
  String? _conversationId;
  List<String> _suggestions = const [];
  bool _sending = false;
  bool _listening = false;

  /// Set when the server could not be reached but the sentence was understood.
  _OfflineOffer? _offer;
  bool _speechReady = false;

  /// Counts down to sending what was just dictated.
  ///
  /// Speaking used to leave the words sitting in the text field, and the person
  /// then had to find the send button — which defeats the point of talking to
  /// the app at all, and is the part a shopkeeper who does not read English
  /// gets stuck on.
  ///
  /// Sending the instant the engine says "final" is not right either: it
  /// decides that after a pause in speech, not after a finished thought, so it
  /// will happily fire off half a sentence — and half a sentence can post a
  /// wrong invoice. A visible countdown does both: say nothing and it sends
  /// itself, touch anything and it waits.
  Timer? _autoSendTimer;
  int _autoSendIn = 0;
  static const _autoSendSeconds = 3;

  @override
  void initState() {
    super.initState();
    _initSpeech();
    if (widget.initialPrompt != null && widget.initialPrompt!.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => _send(widget.initialPrompt!),
      );
    }
  }

  @override
  void dispose() {
    _autoSendTimer?.cancel();
    _input.dispose();
    _scroll.dispose();
    _speech.cancel();
    super.dispose();
  }

  /// Stops the countdown and leaves the words alone so they can be edited.
  void _cancelAutoSend() {
    if (_autoSendTimer == null) return;
    _autoSendTimer?.cancel();
    _autoSendTimer = null;
    if (mounted) setState(() => _autoSendIn = 0);
  }

  void _startAutoSend() {
    _autoSendTimer?.cancel();
    if (_input.text.trim().isEmpty) return;

    setState(() => _autoSendIn = _autoSendSeconds);
    _autoSendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_autoSendIn <= 1) {
        timer.cancel();
        _autoSendTimer = null;
        setState(() => _autoSendIn = 0);
        _send(_input.text, isVoice: true);
        return;
      }
      setState(() => _autoSendIn -= 1);
    });
  }

  Future<void> _initSpeech() async {
    try {
      final available = await _speech.initialize(
        onError: (error) {
          if (!mounted) return;
          _cancelAutoSend();
          setState(() => _listening = false);
        },
        onStatus: (status) {
          if (!mounted || status != 'done') return;
          setState(() => _listening = false);
          // The engine does not always deliver a final onResult before it stops
          // — on some devices it just goes quiet. Without this the words would
          // be left stranded in the field, which is the whole bug.
          if (_input.text.trim().isNotEmpty && _autoSendTimer == null) {
            _startAutoSend();
          }
        },
      );
      if (mounted) setState(() => _speechReady = available);
    } catch (_) {
      // Speech is a bonus — typing always works.
    }
  }

  Future<void> _toggleListening() async {
    if (!_speechReady) {
      // One retry first: initialize() runs at startup, before the microphone
      // permission dialog has been answered, so the first attempt can fail on
      // a phone where voice works perfectly well.
      await _initSpeech();
    }
    if (!mounted) return;
    if (!_speechReady) {
      showError(
        context,
        context.t(
          'Voice input needs microphone permission and Google speech services. '
          'Check Settings → Apps → Karobar → Permissions.',
        ),
      );
      return;
    }

    if (_listening) {
      // Tapping the mic again means "I am done" — send it rather than making
      // them reach for a second button.
      await _speech.stop();
      setState(() => _listening = false);
      if (_input.text.trim().isNotEmpty) _startAutoSend();
      return;
    }

    _cancelAutoSend();
    setState(() => _listening = true);

    await _speech.listen(
      listenOptions: SpeechListenOptions(
        localeId: await _dictationLocale(),
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.dictation,
        // Without these the platform stops after roughly three seconds of
        // silence, cutting people off mid-sentence while they think of the
        // amount. Four is enough to think without the app feeling dead — it was
        // six, which on top of the countdown made finishing take too long.
        listenFor: const Duration(minutes: 2),
        pauseFor: const Duration(seconds: 4),
      ),
      onResult: (result) {
        setState(() {
          _input.text = result.recognizedWords;
          // Keep the caret at the end so they can carry on typing.
          _input.selection = TextSelection.collapsed(offset: _input.text.length);
          if (result.finalResult) _listening = false;
        });
        if (result.finalResult) _startAutoSend();
      },
    );
  }

  /// The dictation locale, verified against what this phone actually has.
  ///
  /// Roman Urdu — what shopkeepers actually speak — is transcribed best by the
  /// English model, so `ur`/`hi` only switch when the device really has that
  /// locale installed. Asking for a missing one silently returns nothing.
  Future<String> _dictationLocale() async {
    final preferred = switch (ref.read(languageProvider)) {
      'ur' => 'ur_PK',
      'hi' => 'hi_IN',
      _ => 'en_US',
    };
    if (preferred == 'en_US') return preferred;

    final available = await _speech.locales();
    final match = available.any((l) => l.localeId.replaceAll('-', '_') == preferred);
    return match ? preferred : 'en_US';
  }

  /// What to do with a sentence the server never got to see.
  ///
  /// Reads the command on the phone and, when it is something that can be done
  /// without a signal, offers to open the screen for it already filled in. The
  /// work itself was never the blocked part: bills, payments and expenses go
  /// into the outbox and upload when the signal comes back.
  ///
  /// Nothing is saved from here. The shopkeeper sees what was understood and
  /// taps, or does not — an entry made silently from a misheard sentence is
  /// found weeks later in the wrong ledger.
  Future<ChatMessage> _offlineFallback(String message, Object error) async {
    ChatMessage plain(String content) => ChatMessage(
          id: 'error-${DateTime.now().microsecondsSinceEpoch}',
          role: 'assistant',
          content: content,
          error: error.toString(),
        );

    final command = readCommand(message);

    if (!command.worksOffline) {
      // A question needs the shop's figures, which is exactly what cannot be
      // reached. Saying which of the two problems it is beats a raw error.
      return plain(
        command.intent == CommandIntent.question
            ? context.t('This one needs a signal — it has to look at your '
                'figures. Everything else still works: try "Ahmed ko 2 kilo '
                'cheeni 500 ka".')
            : error.toString(),
      );
    }

    // Read before the await, because the screen can be closed while the cached
    // party list is being looked through.
    final understood = context.t('No signal, but I understood that. '
        'Tap below to check it and save — it will upload by itself.');

    final party = await _cachedParty(command.nameHint);

    if (mounted) {
      setState(() => _offer = _OfflineOffer(command: command, party: party));
    }
    return plain(understood);
  }

  /// Finds a party in what the phone already holds.
  ///
  /// The list is whatever was last cached, so this is a best effort and says
  /// so by returning null. A name that cannot be placed leaves the screen to
  /// ask rather than putting the entry against the nearest-looking customer.
  Future<Party?> _cachedParty(String? hint) async {
    if (hint == null) return null;
    try {
      final page = await ref.read(partyRepositoryProvider).list(size: 200);
      final index = bestMatch(hint, [for (final p in page.items) p.name]);
      return index == null ? null : page.items[index];
    } catch (_) {
      // Never cached, or the cache is gone. The screen will ask.
      return null;
    }
  }

  /// Opens the screen the command asked for, carrying what was understood.
  Future<void> _actOnOffer(_OfflineOffer offer) async {
    setState(() => _offer = null);
    final command = offer.command;

    switch (command.intent) {
      case CommandIntent.sale:
      case CommandIntent.purchase:
        context.pushNamed(
          Routes.invoiceForm,
          queryParameters: {
            'type': command.intent == CommandIntent.sale ? 'sale' : 'purchase',
            if (offer.party != null) 'party': offer.party!.id,
          },
        );

      case CommandIntent.paymentIn:
      case CommandIntent.paymentOut:
        await showReceivePaymentSheet(
          context,
          ref,
          initialParty: offer.party,
          initialAmount: command.amount,
        );

      case CommandIntent.expense:
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => ExpenseFormScreen(
              initialTitle: command.nameHint,
              initialAmount: command.amount,
            ),
          ),
        );

      case CommandIntent.question:
      case CommandIntent.unknown:
        break; // Never offered in the first place.
    }
  }

  Future<void> _send(String text, {bool isVoice = false}) async {
    final message = text.trim();
    if (message.isEmpty || _sending) return;

    _autoSendTimer?.cancel();
    _autoSendTimer = null;
    _autoSendIn = 0;
    _input.clear();
    setState(() {
      _sending = true;
      _suggestions = const [];
      // Last message's offer belongs to last message.
      _offer = null;
      _messages.add(
        ChatMessage(
          id: 'local-${DateTime.now().microsecondsSinceEpoch}',
          role: 'user',
          content: message,
          createdAt: DateTime.now(),
        ),
      );
      _messages.add(
        const ChatMessage(id: 'typing', role: 'assistant', content: '', isPending: true),
      );
    });
    _scrollToBottom();

    // Known to be off the network: go straight to reading it here rather than
    // spending the shopkeeper's next thirty seconds on a request that cannot
    // arrive, and then telling them so.
    if (!ref.read(syncStateProvider).online) {
      final offline = await _offlineFallback(
        message,
        const _NoSignal(),
      );
      if (!mounted) return;
      setState(() {
        _messages
          ..removeWhere((m) => m.id == 'typing')
          ..add(offline);
        _sending = false;
      });
      _scrollToBottom();
      return;
    }

    try {
      final repository = ref.read(aiRepositoryProvider);
      final reply = isVoice
          ? await repository.voice(transcript: message, conversationId: _conversationId)
          : await repository.chat(
              message: message,
              conversationId: _conversationId,
              language: ref.read(languageProvider),
            );

      if (!mounted) return;
      setState(() {
        _conversationId = reply.conversationId;
        _messages
          ..removeWhere((m) => m.id == 'typing')
          ..add(
            ChatMessage(
              id: reply.messageId,
              role: 'assistant',
              content: reply.reply,
              actions: reply.actions,
              createdAt: DateTime.now(),
            ),
          );
        _suggestions = reply.suggestions;
      });

      // A write happened — every cached list is now stale.
      if (reply.actions.any((a) => a.succeeded && a.entityId != null)) {
        invalidateBusinessData(ref);
      }
    } catch (error) {
      if (!mounted) return;

      // The server could not be reached, or the model is throttled. What the
      // shopkeeper asked for almost always works offline anyway — bills,
      // payments and expenses queue and go up later — so read the sentence
      // here rather than handing back an error and stopping.
      final fallback = await _offlineFallback(message, error);
      if (!mounted) return;

      setState(() {
        _messages
          ..removeWhere((m) => m.id == 'typing')
          ..add(fallback);
      });
    } finally {
      if (mounted) setState(() => _sending = false);
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent + 120,
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final suggestionsAsync = ref.watch(aiSuggestionsProvider);

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              width: 30,
              height: 30,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AppColors.primary, AppColors.primaryDarker],
                ),
                borderRadius: BorderRadius.circular(9),
              ),
              child: const Icon(Icons.auto_awesome, size: 16, color: Colors.white),
            ),
            const SizedBox(width: 10),
            Text(context.t('Assistant')),
          ],
        ),
        actions: [
          if (_messages.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.add_comment_outlined),
              tooltip: context.t('New chat'),
              onPressed: () => setState(() {
                _messages.clear();
                _conversationId = null;
                _suggestions = const [];
              }),
            ),
          IconButton(
            icon: const Icon(Icons.document_scanner_outlined),
            tooltip: context.t('Scan a bill'),
            onPressed: () => context.goNamed(Routes.scan),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty
                ? _Welcome(
                    suggestions: suggestionsAsync.valueOrNull ?? const [],
                    onTap: _send,
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                    itemCount: _messages.length,
                    itemBuilder: (_, index) => _Bubble(message: _messages[index]),
                  ),
          ),

          // Sits directly above the input, where the shopkeeper is already
          // looking after their message failed.
          if (_offer != null)
            _OfferCard(
              offer: _offer!,
              symbol: ref.watch(sessionProvider).symbol,
              onAct: () => _actOnOffer(_offer!),
              onDismiss: () => setState(() => _offer = null),
            ),

          if (_suggestions.isNotEmpty)
            SizedBox(
              height: 44,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
                  for (final suggestion in _suggestions) ...[
                    ActionChip(
                      label: Text(suggestion),
                      onPressed: () => _send(suggestion),
                    ),
                    const SizedBox(width: 8),
                  ],
                ],
              ),
            ),

          if (_autoSendIn > 0) _AutoSendBar(
            seconds: _autoSendIn,
            total: _autoSendSeconds,
            onCancel: _cancelAutoSend,
          ),

          Container(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            decoration: BoxDecoration(
              color: theme.colorScheme.surface,
              border: Border(top: BorderSide(color: theme.colorScheme.outline)),
            ),
            child: SafeArea(
              top: false,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: TextField(
                      controller: _input,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      onSubmitted: _send,
                      // Touching the words means they want to change them, so
                      // the countdown must get out of the way immediately.
                      onChanged: (_) => _cancelAutoSend(),
                      onTap: _cancelAutoSend,
                      decoration: InputDecoration(
                        hintText: _listening
                            ? 'Listening…'
                            : context.tr('ask_anything'),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 12,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  _MicButton(
                    listening: _listening,
                    enabled: _speechReady && !_sending,
                    onTap: _toggleListening,
                  ),
                  const SizedBox(width: 6),
                  SizedBox(
                    width: 46,
                    height: 46,
                    child: FilledButton(
                      onPressed: _sending ? null : () => _send(_input.text),
                      style: FilledButton.styleFrom(
                        padding: EdgeInsets.zero,
                        shape: const CircleBorder(),
                      ),
                      child: _sending
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.arrow_upward, size: 20),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Shown between finishing dictation and the message being sent.
///
/// It exists so that "it will send itself" is something the person can see
/// happening, and stopping it is one obvious tap rather than a guess. The whole
/// bar is the cancel target — a small × would be the wrong size for a thumb on
/// a shop counter.
/// What the phone understood, offered rather than done.
///
/// The shopkeeper reads it back before anything is written. Dismissing is as
/// easy as accepting, because the sentence came off a microphone in a noisy
/// shop and sometimes it will simply be wrong.
class _OfferCard extends StatelessWidget {
  const _OfferCard({
    required this.offer,
    required this.symbol,
    required this.onAct,
    required this.onDismiss,
  });

  final _OfflineOffer offer;
  final String symbol;
  final VoidCallback onAct;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 0),
      child: AppCard(
        padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
        borderColor: AppColors.primary.withValues(alpha: 0.45),
        child: Row(
          children: [
            Icon(offer.icon, size: 20, color: AppColors.primary),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    context.t(offer.title),
                    style: theme.textTheme.labelLarge
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 1),
                  Text(
                    offer.detail(symbol),
                    style: theme.textTheme.bodySmall,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            IconButton(
              icon: const Icon(Icons.close, size: 18),
              visualDensity: VisualDensity.compact,
              tooltip: context.t('Not that'),
              onPressed: onDismiss,
            ),
            FilledButton(
              onPressed: onAct,
              style: FilledButton.styleFrom(minimumSize: const Size(0, 36)),
              child: Text(context.t('Open')),
            ),
          ],
        ),
      ),
    );
  }
}

class _AutoSendBar extends StatelessWidget {
  const _AutoSendBar({
    required this.seconds,
    required this.total,
    required this.onCancel,
  });

  final int seconds;
  final int total;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tint = AppColors.softTint(AppColors.primary, theme.brightness);
    final onTint = AppColors.onSoftTint(AppColors.primary, theme.brightness);

    return Material(
      color: tint,
      child: InkWell(
        onTap: onCancel,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              SizedBox(
                width: 22,
                height: 22,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    TweenAnimationBuilder(
                      tween: Tween<double>(begin: 1, end: seconds / total),
                      duration: const Duration(milliseconds: 900),
                      builder: (_, value, __) => CircularProgressIndicator(
                        value: value,
                        strokeWidth: 2.4,
                        color: onTint,
                        backgroundColor: onTint.withValues(alpha: 0.22),
                      ),
                    ),
                    Text(
                      '$seconds',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w800,
                        color: onTint,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  context.t('Sending in a moment — tap here to edit first'),
                  style: TextStyle(
                    color: onTint,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
              ),
              Icon(Icons.edit_outlined, size: 18, color: onTint),
            ],
          ),
        ),
      ),
    );
  }
}

class _MicButton extends StatelessWidget {
  const _MicButton({
    required this.listening,
    required this.enabled,
    required this.onTap,
  });

  final bool listening;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: context.t(
        listening ? 'Stop and send' : 'Speak instead of typing',
      ),
      child: GestureDetector(
        onTap: enabled ? onTap : null,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          width: 46,
          height: 46,
          decoration: BoxDecoration(
            color: listening
                ? AppColors.danger
                : Theme.of(context).colorScheme.surfaceContainerHighest,
            shape: BoxShape.circle,
            border: Border.all(
              color:
                  listening ? AppColors.danger : Theme.of(context).colorScheme.outline,
            ),
          ),
          child: Icon(
            listening ? Icons.stop : Icons.mic_none,
            size: 21,
            color: listening
                ? Colors.white
                : enabled
                    ? Theme.of(context).colorScheme.onSurface
                    : Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ),
    );
  }
}

class _Welcome extends StatelessWidget {
  const _Welcome({required this.suggestions, required this.onTap});

  final List<String> suggestions;
  final ValueChanged<String> onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 24),
        const Center(child: KarobarMark(size: 64)),
        const SizedBox(height: 20),
        Text(
          'How can I help?',
          textAlign: TextAlign.center,
          style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 8),
        Text(
          'Speak or type in Urdu, Hindi or English.\n'
          'I can create bills, record payments and answer questions about your shop.',
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant, height: 1.5),
        ),
        const SizedBox(height: 28),
        for (final suggestion in suggestions.take(5))
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: AppCard(
              onTap: () => onTap(suggestion),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
              child: Row(
                children: [
                  const Icon(Icons.bolt_outlined, size: 17, color: AppColors.primary),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(suggestion, style: theme.textTheme.bodyMedium),
                  ),
                  Icon(
                    Icons.north_east,
                    size: 14,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUser = message.isUser;

    if (message.isPending) {
      return const Padding(
        padding: EdgeInsets.only(bottom: 14),
        child: Align(alignment: Alignment.centerLeft, child: _TypingDots()),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Container(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.sizeOf(context).width * 0.82,
            ),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: BoxDecoration(
              color: isUser
                  ? AppColors.primary
                  : message.error != null
                      ? AppColors.softTint(AppColors.danger, Theme.of(context).brightness)
                      : theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.only(
                topLeft: const Radius.circular(AppTheme.radius),
                topRight: const Radius.circular(AppTheme.radius),
                bottomLeft: Radius.circular(isUser ? AppTheme.radius : 4),
                bottomRight: Radius.circular(isUser ? 4 : AppTheme.radius),
              ),
            ),
            child: Text(
              message.content,
              style: TextStyle(
                color: isUser
                    ? Colors.white
                    : message.error != null
                        ? AppColors.danger
                        : theme.colorScheme.onSurface,
                height: 1.45,
                fontSize: 15,
              ),
            ),
          ),
          if (message.actions.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final action in message.actions) _ActionChip(action: action),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// A record the assistant created or read, tappable to open it.
class _ActionChip extends StatelessWidget {
  const _ActionChip({required this.action});

  final AiAction action;

  @override
  Widget build(BuildContext context) {
    final failed = !action.succeeded;
    final tint = failed ? AppColors.danger : AppColors.success;
    final tappable = action.deepLink != null && !failed;

    return InkWell(
      onTap: tappable ? () => openDeepLink(context, action.deepLink) : null,
      borderRadius: BorderRadius.circular(999),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
        decoration: BoxDecoration(
          color: tint.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: tint.withValues(alpha: 0.30)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(failed ? Icons.error_outline : Icons.check_circle, size: 13, color: tint),
            const SizedBox(width: 6),
            ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: MediaQuery.sizeOf(context).width * 0.62,
              ),
              child: Text(
                action.summary ?? action.label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: tint,
                ),
              ),
            ),
            if (tappable) ...[
              const SizedBox(width: 4),
              Icon(Icons.chevron_right, size: 14, color: tint),
            ],
          ],
        ),
      ),
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(AppTheme.radius),
          topRight: Radius.circular(AppTheme.radius),
          bottomRight: Radius.circular(AppTheme.radius),
          bottomLeft: Radius.circular(4),
        ),
      ),
      child: AnimatedBuilder(
        animation: _controller,
        builder: (_, __) => Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (index) {
            final phase = (_controller.value - index * 0.18) % 1.0;
            final scale = 0.6 + 0.4 * (phase < 0.5 ? phase * 2 : (1 - phase) * 2);
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2.5),
              child: Transform.scale(
                scale: scale,
                child: const CircleAvatar(radius: 3.5, backgroundColor: AppColors.primary),
              ),
            );
          }),
        ),
      ),
    );
  }
}
