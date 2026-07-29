import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../utils/formatters.dart';

/// A bordered surface — the default container for everything in the app.
class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
    this.color,
    this.borderColor,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final Color? color;
  final Color? borderColor;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final body = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color ?? scheme.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: borderColor ?? scheme.outline),
      ),
      child: child,
    );

    if (onTap == null) return body;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        child: body,
      ),
    );
  }
}

/// An amount, coloured by sign when [signed] is on.
class MoneyText extends StatelessWidget {
  const MoneyText(
    this.value, {
    super.key,
    this.symbol = 'Rs ',
    this.style,
    this.signed = false,
    this.compact = false,
    this.decimals = true,
  });

  final num? value;
  final String symbol;
  final TextStyle? style;
  final bool signed;
  final bool compact;
  final bool decimals;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final text = compact
        ? Fmt.compactMoney(value, symbol: symbol)
        : Fmt.money(value, symbol: symbol, decimals: decimals);

    return Text(
      text,
      style: (style ?? Theme.of(context).textTheme.titleMedium)?.copyWith(
        color: signed ? AppColors.forBalance(value ?? 0, dark: isDark) : style?.color,
        fontFeatures: const [FontFeature.tabularFigures()],
      ),
    );
  }
}

/// Status pill for invoices, stock levels and sync state.
class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key, this.label, this.dense = false});

  final String status;
  final String? label;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final (background, foreground) =
        AppColors.forStatus(status, brightness: Theme.of(context).brightness);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: dense ? 7 : 10,
        vertical: dense ? 2 : 4,
      ),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        (label ?? Fmt.titleCase(status)).toUpperCase(),
        style: TextStyle(
          color: foreground,
          fontSize: dense ? 9 : 10,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

/// Coloured initials avatar, stable per name.
class NameAvatar extends StatelessWidget {
  const NameAvatar(this.name, {super.key, this.size = 44, this.imageUrl});

  final String name;
  final double size;
  final String? imageUrl;

  @override
  Widget build(BuildContext context) {
    final color = AppColors.forName(name);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(size * 0.32),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      alignment: Alignment.center,
      child: Text(
        Fmt.initials(name),
        style: TextStyle(
          color: color,
          fontSize: size * 0.36,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

/// Empty / error state with an optional call to action.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.title,
    this.message,
    this.icon = Icons.inbox_outlined,
    this.actionLabel,
    this.onAction,
    this.isError = false,
  });

  final String title;
  final String? message;
  final IconData icon;
  final String? actionLabel;
  final VoidCallback? onAction;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final accent = isError ? AppColors.danger : AppColors.primary;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 78,
              height: 78,
              decoration: BoxDecoration(
                color: accent.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(24),
              ),
              child: Icon(isError ? Icons.error_outline : icon, size: 36, color: accent),
            ),
            const SizedBox(height: 18),
            Text(
              title,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            if (message != null) ...[
              const SizedBox(height: 6),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            if (onAction != null && actionLabel != null) ...[
              const SizedBox(height: 20),
              SizedBox(
                width: 200,
                child: FilledButton(onPressed: onAction, child: Text(actionLabel!)),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Skeleton rows shown while a list loads.
class ListSkeleton extends StatelessWidget {
  const ListSkeleton({super.key, this.rows = 6, this.height = 76});

  final int rows;
  final double height;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Shimmer.fromColors(
      baseColor: isDark ? AppColors.darkSurfaceAlt : AppColors.surfaceAlt,
      highlightColor: isDark ? AppColors.darkBorder : AppColors.divider,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        physics: const NeverScrollableScrollPhysics(),
        itemCount: rows,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (_, __) => Container(
          height: height,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(AppTheme.radius),
          ),
        ),
      ),
    );
  }
}

/// Small section title with an optional trailing action.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.actionLabel, this.onAction});

  final String title;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 20, 8, 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ),
          if (actionLabel != null)
            TextButton(onPressed: onAction, child: Text(actionLabel!)),
        ],
      ),
    );
  }
}

/// A labelled figure used across the dashboard and report screens.
class StatTile extends StatelessWidget {
  const StatTile({
    super.key,
    required this.label,
    required this.value,
    this.changePercent,
    this.icon,
    this.accent,
    this.onTap,
  });

  final String label;
  final String value;
  final num? changePercent;
  final IconData? icon;
  final Color? accent;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tint = accent ?? AppColors.primary;
    final change = changePercent;

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              if (icon != null) ...[
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: tint.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, size: 15, color: tint),
                ),
                const SizedBox(width: 8),
              ],
              Expanded(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w800,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
          if (change != null) ...[
            const SizedBox(height: 4),
            Row(
              children: [
                Icon(
                  change >= 0 ? Icons.trending_up : Icons.trending_down,
                  size: 13,
                  color: change >= 0 ? AppColors.success : AppColors.danger,
                ),
                const SizedBox(width: 3),
                Text(
                  '${change.abs().toStringAsFixed(1)}%',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: change >= 0 ? AppColors.success : AppColors.danger,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// Icon + label button used in the quick-actions grid.
class ActionTile extends StatelessWidget {
  const ActionTile({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.color,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final tint = color ?? AppColors.primary;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppTheme.radius),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 50,
              height: 50,
              decoration: BoxDecoration(
                color: tint.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Icon(icon, color: tint, size: 23),
            ),
            const SizedBox(height: 8),
            // Flexible, not a bare Text: the grid gives every tile a fixed
            // height, and at a large system font size two lines of label are
            // taller than the cell. Letting the label shrink turns a yellow
            // overflow stripe into an ellipsis.
            Flexible(
              child: Text(
                label,
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                      height: 1.25,
                    ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Height one tile needs at the current text size.
  ///
  /// Callers lay these out in a grid, which wants an explicit extent — deriving
  /// it from the text scaler is what keeps the tiles correct for someone running
  /// their phone at 130% font size.
  static double extentFor(BuildContext context) {
    const iconBox = 50.0, gap = 8.0, verticalPadding = 24.0, lineHeight = 11 * 1.25;
    final scale = MediaQuery.textScalerOf(context).scale(1);
    return iconBox + gap + verticalPadding + (lineHeight * 2 * scale) + 2;
  }
}

/// A small unread counter. Anything past 9 reads as "9+" so the pill keeps its
/// width no matter how far behind the shopkeeper is.
class CountBadge extends StatelessWidget {
  const CountBadge(this.count, {super.key, this.color = AppColors.danger});

  final int count;
  final Color color;

  @override
  Widget build(BuildContext context) {
    if (count <= 0) return const SizedBox.shrink();
    return Container(
      constraints: const BoxConstraints(minWidth: 18),
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(999)),
      child: Text(
        count > 9 ? '9+' : '$count',
        textAlign: TextAlign.center,
        style: const TextStyle(
          color: AppColors.white,
          fontSize: 10,
          fontWeight: FontWeight.w800,
          height: 1.3,
        ),
      ),
    );
  }
}

/// Shows an error as a snackbar with a consistent look.
void showError(BuildContext context, Object error) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Row(
          children: [
            const Icon(Icons.error_outline, color: AppColors.white, size: 18),
            const SizedBox(width: 10),
            Expanded(child: Text(error.toString())),
          ],
        ),
        backgroundColor: AppColors.danger,
      ),
    );
}

void showSuccess(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Row(
          children: [
            const Icon(Icons.check_circle_outline, color: AppColors.white, size: 18),
            const SizedBox(width: 10),
            Expanded(child: Text(message)),
          ],
        ),
        backgroundColor: AppColors.success,
      ),
    );
}
