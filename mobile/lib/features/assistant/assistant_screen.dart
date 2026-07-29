import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../data/models.dart';
import '../../providers.dart';

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
  bool _speechReady = false;

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
    _input.dispose();
    _scroll.dispose();
    _speech.cancel();
    super.dispose();
  }

  Future<void> _initSpeech() async {
    try {
      final available = await _speech.initialize(
        onError: (error) {
          if (mounted) setState(() => _listening = false);
        },
        onStatus: (status) {
          if (mounted && status == 'done') setState(() => _listening = false);
        },
      );
      if (mounted) setState(() => _speechReady = available);
    } catch (_) {
      // Speech is a bonus — typing always works.
    }
  }

  Future<void> _toggleListening() async {
    if (!_speechReady) {
      showError(context, 'Voice input is not available on this device.');
      return;
    }

    if (_listening) {
      await _speech.stop();
      setState(() => _listening = false);
      return;
    }

    setState(() => _listening = true);

    await _speech.listen(
      listenOptions: SpeechListenOptions(
        localeId: await _dictationLocale(),
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.dictation,
        // Without these the platform stops after roughly three seconds of
        // silence, cutting people off mid-sentence while they think of the
        // amount.
        listenFor: const Duration(minutes: 2),
        pauseFor: const Duration(seconds: 6),
      ),
      onResult: (result) {
        setState(() {
          _input.text = result.recognizedWords;
          // Keep the caret at the end so they can carry on typing.
          _input.selection = TextSelection.collapsed(offset: _input.text.length);
          if (result.finalResult) _listening = false;
        });
        // Deliberately NOT sent automatically. The engine decides "final" after
        // a pause, not after a finished thought — auto-sending fires off half a
        // sentence and, worse, can post a wrong invoice. They press send.
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

  Future<void> _send(String text, {bool isVoice = false}) async {
    final message = text.trim();
    if (message.isEmpty || _sending) return;

    _input.clear();
    setState(() {
      _sending = true;
      _suggestions = const [];
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
      setState(() {
        _messages
          ..removeWhere((m) => m.id == 'typing')
          ..add(
            ChatMessage(
              id: 'error-${DateTime.now().microsecondsSinceEpoch}',
              role: 'assistant',
              content: error.toString(),
              error: error.toString(),
            ),
          );
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
    return GestureDetector(
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
            color: listening ? AppColors.danger : Theme.of(context).colorScheme.outline,
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
