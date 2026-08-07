import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/config/env.dart';
import '../../core/l10n/strings.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/widgets/common.dart';
import '../../core/widgets/karobar_logo.dart';
import '../../providers.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final language = ref.watch(languageProvider);
    final themeMode = ref.watch(themeModeProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('settings'))),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: AppCard(
              child: Row(
                children: [
                  NameAvatar(session.user?.name ?? '?', size: 52),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          session.user?.name ?? 'User',
                          style: theme.textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        Text(
                          session.user?.email ?? session.user?.phone ?? '',
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                        ),
                        if (session.business?.role != null) ...[
                          const SizedBox(height: 5),
                          StatusChip('draft', label: session.business!.role!, dense: true),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),

          if (session.businesses.length > 1) ...[
            const SectionHeader('Your businesses'),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: AppCard(
                padding: EdgeInsets.zero,
                child: Column(
                  children: [
                    for (final (index, business) in session.businesses.indexed) ...[
                      if (index > 0) const Divider(height: 1),
                      ListTile(
                        leading: NameAvatar(business.name, size: 36),
                        title: Text(business.name),
                        subtitle: Text(
                          '${business.businessType} · ${business.currency}',
                        ),
                        trailing: business.id == session.business?.id
                            ? const Icon(Icons.check_circle, color: AppColors.success)
                            : null,
                        onTap: business.id == session.business?.id
                            ? null
                            : () async {
                                try {
                                  await ref
                                      .read(sessionProvider.notifier)
                                      .switchBusiness(business.id);
                                  if (!context.mounted) return;
                                  invalidateBusinessData(ref);
                                  showSuccess(context, 'Switched to ${business.name}.');
                                } catch (error) {
                                  if (context.mounted) showError(context, error);
                                }
                              },
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],

          const SectionHeader('App'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.translate),
                    title: Text(context.t('Language')),
                    subtitle: Text(Strings.languageNames[language] ?? 'English'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _pickLanguage(context, ref, language),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.brightness_6_outlined),
                    title: Text(context.t('Appearance')),
                    subtitle: Text(switch (themeMode) {
                      ThemeMode.light => 'Light',
                      ThemeMode.dark => 'Dark',
                      ThemeMode.system => 'Match my phone',
                    }),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _pickTheme(context, ref, themeMode),
                  ),
                ],
              ),
            ),
          ),

          const SectionHeader('Manage'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.receipt_outlined),
                    title: Text(context.tr('expenses')),
                    subtitle: const Text('Rent, salaries, transport, utilities'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.expenses),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.payments_outlined),
                    title: Text(context.t('Payments')),
                    subtitle: const Text('Everything received and paid out'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.payments),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.account_balance_outlined),
                    title: Text(context.t('Cash & bank')),
                    subtitle: const Text('Accounts, and money moved between them'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.accounts),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.receipt_long_outlined),
                    title: Text(context.t('Cheques')),
                    subtitle: const Text('What is still to deposit or clear'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.cheques),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.request_quote_outlined),
                    title: Text(context.t('Loans')),
                    subtitle: const Text('What you owe, and the instalments'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.loans),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.warehouse_outlined),
                    title: Text(context.t('Stock locations')),
                    subtitle: const Text('Godowns and branches, and transfers between them'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.godowns),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.event_busy_outlined),
                    title: Text(context.t('Expiring stock')),
                    subtitle: const Text('Batches that have expired or are about to'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.expiry),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.qr_code_2_outlined),
                    title: Text(context.t('Barcode labels')),
                    subtitle: const Text('Print stickers for shelves and packets'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.labels),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.palette_outlined),
                    title: Text(context.t('Invoice look')),
                    subtitle: const Text('How your bills print — 26 to choose from'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.invoiceTheme),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.notifications_outlined),
                    title: Text(context.t('Alerts')),
                    subtitle: const Text('Overdue bills and low stock'),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        ref.watch(unreadCountProvider).maybeWhen(
                              data: (count) => count == 0
                                  ? const SizedBox.shrink()
                                  : CountBadge(count),
                              orElse: () => const SizedBox.shrink(),
                            ),
                        const Icon(Icons.chevron_right),
                      ],
                    ),
                    onTap: () => context.goNamed(Routes.notifications),
                  ),
                ],
              ),
            ),
          ),

          const SectionHeader('Business'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.storefront_outlined),
                    title: const Text('Shop details'),
                    subtitle: Text(session.business?.name ?? '—'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.businessSettings),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.groups_outlined),
                    title: Text(context.t('Team')),
                    subtitle: const Text('Share this shop with your staff'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.team),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.folder_zip_outlined),
                    title: Text(context.t('Your data')),
                    subtitle: const Text('Backup, restore, GST export'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => context.goNamed(Routes.data),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    leading: const Icon(Icons.chat_outlined),
                    title: const Text('WhatsApp & email'),
                    subtitle: const Text('Send bills and payment reminders'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _showIntegrations(context, ref),
                  ),
                ],
              ),
            ),
          ),

          const SectionHeader('About'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: AppCard(
              child: Column(
                children: [
                  const KarobarLogo(size: LogoSize.medium, direction: Axis.vertical),
                  const SizedBox(height: 14),
                  Text(
                    'Version ${Env.version}',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                  // The build, so "does the APK you are running contain this
                  // fix?" is something anyone can answer by looking, instead of
                  // being inferred from whether a bug still reproduces.
                  SelectableText(
                    'Build ${Env.buildStamp}',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 2),
                  SelectableText(
                    Env.apiBaseUrl,
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 24),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.danger,
                side: const BorderSide(color: AppColors.danger),
              ),
              onPressed: () => _signOut(context, ref),
              icon: const Icon(Icons.logout, size: 20),
              label: Text(context.tr('sign_out')),
            ),
          ),
        ],
      ),
    );
  }

  /// Read-only view of which delivery channels are live. Connecting Gmail is an
  /// OAuth round-trip, so it hands off to the browser and comes back via the
  /// `karobar://` deep link.
  Future<void> _showIntegrations(BuildContext context, WidgetRef ref) async {
    Map<String, dynamic> status;
    try {
      status = await ref.read(businessRepositoryProvider).integrations();
    } catch (error) {
      if (context.mounted) showError(context, error);
      return;
    }
    if (!context.mounted) return;

    final gmail = Map<String, dynamic>.from(status['gmail'] as Map? ?? {});
    final whatsapp = Map<String, dynamic>.from(status['whatsapp'] as Map? ?? {});
    final smtp = Map<String, dynamic>.from(status['smtp_fallback'] as Map? ?? {});

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Sending bills & reminders',
                style: Theme.of(sheetContext).textTheme.titleLarge,
              ),
              const SizedBox(height: 14),
              _ChannelTile(
                icon: Icons.chat,
                label: 'WhatsApp',
                connected: whatsapp['connected'] == true,
                detail: whatsapp['connected'] == true
                    ? 'Bills and reminders send from ${whatsapp['phone_number_id'] ?? 'your business number'}'
                    : 'Ask your admin to add the WhatsApp Business token on the server',
              ),
              const Divider(height: 20),
              _ChannelTile(
                icon: Icons.mail_outline,
                label: 'Gmail',
                connected: gmail['connected'] == true,
                detail: gmail['connected'] == true
                    ? 'Sending as ${gmail['account'] ?? 'your Google account'}'
                    : 'Connect your Google account to email bills from your own address',
                action: gmail['connected'] == true
                    ? null
                    : TextButton(
                        onPressed: () async {
                          Navigator.pop(sheetContext);
                          await _connectGmail(context, ref);
                        },
                        child: Text(context.t('Connect')),
                      ),
              ),
              const Divider(height: 20),
              _ChannelTile(
                icon: Icons.alternate_email,
                label: 'Email fallback',
                connected: smtp['configured'] == true,
                detail: smtp['configured'] == true
                    ? 'Used when Gmail is not connected'
                    : 'No SMTP server configured',
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _connectGmail(BuildContext context, WidgetRef ref) async {
    try {
      final data = await ref.read(apiClientProvider).get('/integrations/gmail/connect');
      final url = Uri.parse((data as Map)['authorize_url'].toString());
      if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
        throw 'Could not open the browser.';
      }
    } catch (error) {
      if (context.mounted) showError(context, error);
    }
  }

  Future<void> _pickLanguage(BuildContext context, WidgetRef ref, String current) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 12),
            Text('Language', style: Theme.of(sheetContext).textTheme.titleLarge),
            const SizedBox(height: 12),
            for (final entry in Strings.languageNames.entries)
              ListTile(
                title: Text(
                  entry.value,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                // The sample is the real signal: people recognise how they talk
                // faster than they recognise a language's name.
                subtitle: Text(
                  Strings.languageSamples[entry.key] ?? '',
                  style: const TextStyle(fontSize: 12),
                ),
                trailing: entry.key == current
                    ? const Icon(Icons.check_circle, color: AppColors.primary)
                    : null,
                onTap: () => Navigator.pop(sheetContext, entry.key),
              ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
    if (choice != null) await ref.read(languageProvider.notifier).set(choice);
  }

  Future<void> _pickTheme(BuildContext context, WidgetRef ref, ThemeMode current) async {
    final choice = await showModalBottomSheet<ThemeMode>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 12),
            Text('Appearance', style: Theme.of(sheetContext).textTheme.titleLarge),
            const SizedBox(height: 12),
            for (final entry in const {
              ThemeMode.system: 'Match my phone',
              ThemeMode.light: 'Light',
              ThemeMode.dark: 'Dark',
            }.entries)
              ListTile(
                title: Text(entry.value),
                trailing: entry.key == current
                    ? const Icon(Icons.check_circle, color: AppColors.primary)
                    : null,
                onTap: () => Navigator.pop(sheetContext, entry.key),
              ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
    if (choice != null) await ref.read(themeModeProvider.notifier).set(choice);
  }

  Future<void> _signOut(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will need your password or a code to sign back in.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Stay signed in'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Sign out'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    await ref.read(sessionProvider.notifier).signOut();
    if (context.mounted) context.go('/login');
  }
}

class _ChannelTile extends StatelessWidget {
  const _ChannelTile({
    required this.icon,
    required this.label,
    required this.connected,
    required this.detail,
    this.action,
  });

  final IconData icon;
  final String label;
  final bool connected;
  final String detail;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tint = connected ? AppColors.success : theme.colorScheme.onSurfaceVariant;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 21, color: tint),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Text(
                    label,
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(width: 8),
                  StatusChip(
                    connected ? 'paid' : 'draft',
                    label: connected ? 'Connected' : 'Not set up',
                    dense: true,
                  ),
                ],
              ),
              const SizedBox(height: 3),
              Text(
                detail,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
        if (action != null) action!,
      ],
    );
  }
}
