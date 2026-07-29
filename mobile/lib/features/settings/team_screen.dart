import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/l10n/strings.dart';
import '../../core/widgets/common.dart';
import '../../data/models.dart';
import '../../providers.dart';

/// Everyone who shares this shop.
///
/// Invites deliberately have no link to click: the server creates a placeholder
/// account against the email or phone number, and the person claims it simply by
/// signing in with that same email or number. Nothing to forward, nothing to
/// expire, and it works for someone who only has WhatsApp.
class TeamScreen extends ConsumerWidget {
  const TeamScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(teamMembersProvider);
    final session = ref.watch(sessionProvider);
    final canManage = session.can('member:manage');

    return Scaffold(
      appBar: AppBar(title: Text(context.t('Team'))),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(teamMembersProvider),
        child: async.when(
          loading: () => const ListSkeleton(rows: 4, height: 76),
          error: (error, _) => EmptyState(
            title: 'Could not load your team',
            message: error.toString(),
            isError: true,
            actionLabel: 'Retry',
            onAction: () => ref.invalidate(teamMembersProvider),
          ),
          data: (members) => ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
            children: [
              AppCard(
                color: AppColors.softTint(AppColors.primary, Theme.of(context).brightness),
                borderColor: AppColors.primary.withValues(alpha: 0.28),
                child: Row(
                  children: [
                    const Icon(Icons.groups_outlined, size: 20, color: AppColors.primaryDarker),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Everyone here sees the same customers, stock and bills. '
                        'What they can change depends on their role.',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(height: 1.45),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              for (final member in members)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _MemberRow(
                    member: member,
                    canManage: canManage,
                    isSelf: member.userId == session.user?.id,
                  ),
                ),
              if (!canManage) ...[
                const SizedBox(height: 8),
                Text(
                  'Only the owner and managers can add or remove people.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ],
            ],
          ),
        ),
      ),
      floatingActionButton: canManage
          ? FloatingActionButton.extended(
              heroTag: 'team-add',
              onPressed: () => _invite(context, ref),
              icon: const Icon(Icons.person_add_alt),
              label: Text(context.t('Add someone')),
            )
          : null,
    );
  }

  Future<void> _invite(BuildContext context, WidgetRef ref) async {
    final added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _InviteSheet(),
    );
    if (added == true) ref.invalidate(teamMembersProvider);
  }
}

class _MemberRow extends ConsumerWidget {
  const _MemberRow({
    required this.member,
    required this.canManage,
    required this.isSelf,
  });

  final TeamMember member;
  final bool canManage;
  final bool isSelf;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final role = TeamRole.of(member.role);

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          NameAvatar(member.displayName, size: 42),
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
                        member.displayName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (isSelf) ...[
                      const SizedBox(width: 6),
                      Text(
                        '(you)',
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  member.contact,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    StatusChip(
                      member.role == 'owner' ? 'paid' : 'draft',
                      label: role.label,
                      dense: true,
                    ),
                    if (member.isPending) ...[
                      const SizedBox(width: 6),
                      const StatusChip('overdue', label: 'Not joined yet', dense: true),
                    ],
                    if (!member.isActive) ...[
                      const SizedBox(width: 6),
                      const StatusChip('cancelled', label: 'Paused', dense: true),
                    ],
                  ],
                ),
              ],
            ),
          ),
          if (canManage && !isSelf)
            PopupMenuButton<String>(
              icon: const Icon(Icons.more_vert, size: 20),
              onSelected: (value) => _act(context, ref, value),
              itemBuilder: (_) => [
                PopupMenuItem(value: 'role', child: Text(context.t('Change role'))),
                PopupMenuItem(
                  value: 'toggle',
                  child: Text(member.isActive ? 'Pause access' : 'Restore access'),
                ),
                const PopupMenuItem(
                  value: 'remove',
                  child: Text('Remove', style: TextStyle(color: AppColors.danger)),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Future<void> _act(BuildContext context, WidgetRef ref, String action) async {
    final repository = ref.read(businessRepositoryProvider);
    try {
      switch (action) {
        case 'role':
          final role = await _pickRole(context, current: member.role);
          if (role == null) return;
          await repository.updateMember(member.id, role: role);

        case 'toggle':
          await repository.updateMember(member.id, isActive: !member.isActive);

        case 'remove':
          final confirmed = await showDialog<bool>(
            context: context,
            builder: (dialogContext) => AlertDialog(
              title: Text('Remove ${member.displayName}?'),
              content: const Text(
                'They lose access to this shop immediately. Bills and payments '
                'they already recorded stay exactly as they are.',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext, false),
                  child: Text(context.t('Keep them')),
                ),
                FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
                  onPressed: () => Navigator.pop(dialogContext, true),
                  child: Text(context.t('Remove')),
                ),
              ],
            ),
          );
          if (confirmed != true) return;
          await repository.removeMember(member.id);
      }

      if (!context.mounted) return;
      ref.invalidate(teamMembersProvider);
      showSuccess(context, 'Team updated.');
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  Future<String?> _pickRole(BuildContext context, {required String current}) {
    return showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(0, 16, 0, 20),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text(
                'What can they do?',
                style: Theme.of(sheetContext).textTheme.titleLarge,
              ),
            ),
            const SizedBox(height: 10),
            for (final role in TeamRole.all)
              ListTile(
                title: Text(role.label, style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text(role.summary, style: const TextStyle(fontSize: 12)),
                trailing: role.value == current
                    ? const Icon(Icons.check_circle, color: AppColors.primary)
                    : null,
                onTap: () => Navigator.pop(sheetContext, role.value),
              ),
          ],
        ),
      ),
    );
  }
}

class _InviteSheet extends ConsumerStatefulWidget {
  const _InviteSheet();

  @override
  ConsumerState<_InviteSheet> createState() => _InviteSheetState();
}

class _InviteSheetState extends ConsumerState<_InviteSheet> {
  final _formKey = GlobalKey<FormState>();
  final _contact = TextEditingController();
  final _name = TextEditingController();

  String _role = 'salesman';
  bool _busy = false;

  @override
  void dispose() {
    _contact.dispose();
    _name.dispose();
    super.dispose();
  }

  bool get _looksLikeEmail => _contact.text.contains('@');

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);

    final contact = _contact.text.trim();
    try {
      await ref.read(businessRepositoryProvider).inviteMember(
            email: _looksLikeEmail ? contact : null,
            phone: _looksLikeEmail ? null : contact,
            name: _name.text.trim(),
            role: _role,
          );
      if (!mounted) return;
      Navigator.pop(context, true);
      showSuccess(
        context,
        'Added. They get in by signing in with $contact.',
      );
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(
        child: Form(
          key: _formKey,
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
            children: [
              Text('Add someone', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 6),
              Text(
                'They join by signing in with the same email or number — there is '
                'no link to send.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 18),
              TextFormField(
                controller: _contact,
                autofocus: true,
                keyboardType: TextInputType.emailAddress,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  labelText: context.t('Email or phone number'),
                  prefixIcon: Icon(
                    _looksLikeEmail ? Icons.mail_outline : Icons.phone_outlined,
                  ),
                ),
                validator: (value) => (value == null || value.trim().length < 5)
                    ? 'Enter their email or phone number'
                    : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(
                  labelText: 'Their name (optional)',
                  prefixIcon: Icon(Icons.person_outline),
                ),
              ),
              const SizedBox(height: 20),
              Text('What can they do?', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              // Owner is excluded: transferring ownership is a different decision
              // from adding a colleague, and doing it by accident is unrecoverable.
              RadioGroup<String>(
                groupValue: _role,
                onChanged: (value) => setState(() => _role = value ?? _role),
                child: Column(
                  children: [
                    for (final role in TeamRole.all.where((r) => r.value != 'owner'))
                      RadioListTile<String>(
                        value: role.value,
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        title: Text(
                          role.label,
                          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                        ),
                        subtitle: Text(role.summary, style: const TextStyle(fontSize: 11.5)),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : Text(context.t('Add to my shop')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
