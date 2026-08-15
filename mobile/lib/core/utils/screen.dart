import 'package:flutter/material.dart';

/// How much room this screen actually has.
///
/// Karobar was built for a phone and then put in a browser and on a desktop,
/// where a phone layout does not merely look wrong — it is harder to use. A
/// list of bills stretched to 1900 pixels puts the customer's name and the
/// amount at opposite ends of the desk, and the eye cannot carry a row that
/// far. A form one field per line wastes two thirds of the window and pushes
/// the save button below the fold.
///
/// Three sizes, because there are three real situations: a phone in one hand,
/// a tablet or a small window, and a shop computer with the window maximised.
/// Anything finer would be a guess.
enum ScreenSize {
  /// A phone. What every screen was designed for.
  compact,

  /// A tablet, a split window, a small browser.
  medium,

  /// A desktop or a maximised browser window.
  expanded;

  bool get isCompact => this == ScreenSize.compact;
  bool get isWide => this != ScreenSize.compact;

  /// Whether navigation should sit down the side instead of along the bottom.
  ///
  /// A bottom bar on a wide screen puts the buttons a hand's width apart at the
  /// very bottom of the window, which on a desk is the furthest point from
  /// where anyone is looking.
  bool get usesSideRail => this != ScreenSize.compact;

  /// How many columns a form should lay its fields out in.
  int get formColumns => this == ScreenSize.expanded ? 2 : 1;
}

/// Breakpoints, in logical pixels.
///
/// 600 is where a phone in landscape and a small tablet part company; 1024 is
/// about where a browser window stops being a tall strip. Both are the values
/// Material itself uses, which matters mainly because it makes them somebody
/// else's problem to justify.
const double _mediumFrom = 600;
const double _expandedFrom = 1024;

extension ScreenContext on BuildContext {
  ScreenSize get screen {
    final width = MediaQuery.sizeOf(this).width;
    if (width >= _expandedFrom) return ScreenSize.expanded;
    if (width >= _mediumFrom) return ScreenSize.medium;
    return ScreenSize.compact;
  }

  bool get isWideScreen => screen.isWide;
}

/// Keeps a column of content readable however wide the window gets.
///
/// Text stops being readable somewhere past about 70 characters a line, and a
/// list row stops being scannable long before that — the name and the figure
/// end up too far apart to take in together. So content stops growing and
/// centres itself, the way every document on the web does.
///
/// On a phone this is nothing at all: the constraint is never reached, so the
/// widget adds no padding and no layout of its own.
class ReadableWidth extends StatelessWidget {
  const ReadableWidth({
    super.key,
    required this.child,
    this.maxWidth = 900,
    this.padHorizontally = true,
  });

  final Widget child;

  /// 900 suits a list or a form. A wide table or a dashboard of tiles can ask
  /// for more, because those genuinely use the room.
  final double maxWidth;

  /// Off when the child already has its own horizontal padding.
  final bool padHorizontally;

  @override
  Widget build(BuildContext context) {
    // The room this widget actually has, not the width of the window. Inside
    // the shell a navigation rail has already taken its share, and measuring
    // the window would add padding to a column that was never wide enough to
    // need it.
    return LayoutBuilder(
      builder: (context, constraints) {
        final available = constraints.maxWidth;
        if (!available.isFinite || available <= maxWidth) return child;

        return Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: maxWidth),
            child: padHorizontally
                ? Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: child,
                  )
                : child,
          ),
        );
      },
    );
  }
}

/// Lays fields out side by side when there is room, and stacked when there is
/// not.
///
/// Forms in this app are written as a list of fields. On a desktop that leaves
/// a column of inputs down the middle of an empty window with the save button
/// pushed off the bottom — so pairs of related fields share a row instead.
class FormRow extends StatelessWidget {
  const FormRow({super.key, required this.children, this.spacing = 12});

  final List<Widget> children;
  final double spacing;

  @override
  Widget build(BuildContext context) {
    if (children.isEmpty) return const SizedBox.shrink();
    if (children.length == 1) return children.first;

    if (context.screen.formColumns == 1) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) SizedBox(height: spacing),
            children[i],
          ],
        ],
      );
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < children.length; i++) ...[
          if (i > 0) SizedBox(width: spacing),
          Expanded(child: children[i]),
        ],
      ],
    );
  }
}
