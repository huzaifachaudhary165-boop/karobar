import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../data/models.dart';
import 'formatters.dart';

/// Getting hold of somebody who owes money.
///
/// Three ways, because a shop uses all three and for different people: the
/// regular customer gets a call, the one who does not pick up gets a WhatsApp
/// they cannot pretend not to have seen, and the business account gets an
/// email with the figure in writing.
///
/// Written once and shared, because the same three buttons belong on the
/// customer's own screen and on the list of everybody who owes — and two copies
/// of a WhatsApp message drift until one of them says something the shop would
/// not want sent.
abstract final class Chase {
  /// What the shop says when it asks. Polite, and with the figure in it, so
  /// the customer does not have to reply asking how much.
  static String message(Party party, String symbol) =>
      'Assalam-o-alaikum ${party.name},\n\n'
      'Aap ka balance ${Fmt.money(party.balance.abs(), symbol: symbol, decimals: false)} hai. '
      'Baraye meherbani adaigi karein. Shukriya.';

  static bool canCall(Party party) => (party.phone ?? '').trim().isNotEmpty;

  static bool canEmail(Party party) => (party.email ?? '').trim().isNotEmpty;

  static Future<void> call(Party party) async {
    final phone = party.phone?.trim();
    if (phone == null || phone.isEmpty) return;
    final uri = Uri.parse('tel:$phone');
    if (await canLaunchUrl(uri)) await launchUrl(uri);
  }

  static Future<void> whatsapp(Party party, String symbol) async {
    // WhatsApp wants digits only — a number saved as "0300-1234567" opens a
    // chat with nobody otherwise.
    final phone = party.phone?.replaceAll(RegExp(r'[^\d]'), '');
    if (phone == null || phone.isEmpty) return;
    final uri = Uri.parse(
      'https://wa.me/$phone?text=${Uri.encodeComponent(message(party, symbol))}',
    );
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  static Future<void> email(Party party, String symbol) async {
    final address = party.email?.trim();
    if (address == null || address.isEmpty) return;
    final uri = Uri(
      scheme: 'mailto',
      path: address,
      queryParameters: {
        'subject': 'Balance reminder',
        'body': message(party, symbol),
      },
    );
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}

/// Call, WhatsApp and email, as three small buttons.
///
/// A way that is not available is left out rather than shown greyed: a shop
/// that never took the customer's email does not need to be reminded of it
/// every time they want to phone them.
class ChaseButtons extends StatelessWidget {
  const ChaseButtons({
    super.key,
    required this.party,
    required this.symbol,
    this.dense = false,
  });

  final Party party;
  final String symbol;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final size = dense ? 18.0 : 20.0;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (Chase.canCall(party)) ...[
          IconButton(
            icon: Icon(Icons.call, size: size),
            color: const Color(0xFF10B981),
            tooltip: 'Call',
            visualDensity: dense ? VisualDensity.compact : null,
            onPressed: () => Chase.call(party),
          ),
          IconButton(
            icon: Icon(Icons.chat, size: size),
            color: const Color(0xFF25D366), // WhatsApp's own green
            tooltip: 'WhatsApp',
            visualDensity: dense ? VisualDensity.compact : null,
            onPressed: () => Chase.whatsapp(party, symbol),
          ),
        ],
        if (Chase.canEmail(party))
          IconButton(
            icon: Icon(Icons.mail_outline, size: size),
            color: const Color(0xFFEA4335), // Gmail red
            tooltip: 'Email',
            visualDensity: dense ? VisualDensity.compact : null,
            onPressed: () => Chase.email(party, symbol),
          ),
      ],
    );
  }
}
