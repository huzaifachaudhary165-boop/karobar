/// Reading a spoken command without a server.
///
/// The assistant is a 21-tool agent and it lives on the server, so with no
/// signal — or when the model is throttled — a shopkeeper who says "Ahmed ko
/// do kilo cheeni paanch sau ka" gets an error and nothing else. Everything
/// they asked for already works offline: bills, payments and expenses queue in
/// the outbox and go up when the signal comes back. The only missing piece was
/// understanding the sentence.
///
/// This does that with rules, not a model. Nothing is downloaded and nothing
/// runs on the phone's CPU for seconds at a time.
///
/// It reads Roman Urdu the way the postpositions actually work, because that
/// is where the meaning sits:
///
///   "Ahmed **ne** 5000 diye"  → Ahmed gave  → money in
///   "Ahmed **ko** 5000 diye"  → gave to Ahmed → money out
///   "Ahmed **se** 5000 liye"  → took from Ahmed → money in
///
/// The same verb, three different entries in the shop's books. A keyword list
/// that only looked for "diye" would post two of these backwards.
///
/// What it deliberately does not do is guess. A sentence it cannot place comes
/// back as [CommandIntent.unknown] and the caller asks. In a billing app a
/// confident wrong answer is worse than an honest question — it lands in a real
/// shop's ledger and is found weeks later.
library;

/// What the shopkeeper is trying to do.
enum CommandIntent {
  /// Goods going out — a bill.
  sale,

  /// Goods coming in from a supplier.
  purchase,

  /// Money received.
  paymentIn,

  /// Money paid out.
  paymentOut,

  /// Shop expense — electricity, rent, tea.
  expense,

  /// They are asking something, which needs the server.
  question,

  /// Not placed. The caller asks rather than guessing.
  unknown,
}

/// What a sentence turned out to be.
class OfflineCommand {
  const OfflineCommand({
    required this.intent,
    required this.original,
    this.amount,
    this.qty,
    this.unit,
    this.nameHint,
  });

  final CommandIntent intent;
  final String original;

  /// Rupees, when the sentence carried a figure that is not a count.
  final num? amount;

  /// How many, when a number was followed by a unit.
  final num? qty;

  /// The unit as it was said — "kilo", "packet" — for the line it becomes.
  final String? unit;

  /// The words most likely naming a customer, supplier or item.
  ///
  /// Not resolved to anything here: the phone already holds the shop's own
  /// parties and items, and matching against that real list beats anything
  /// this could infer from the sentence alone.
  final String? nameHint;

  /// Whether this is worth acting on at all.
  bool get isUnderstood => intent != CommandIntent.unknown;

  /// Whether it can be handled without a server.
  ///
  /// A question needs data this cannot reach. Everything else becomes a screen
  /// the shopkeeper can fill in and save into the outbox.
  bool get worksOffline =>
      isUnderstood && intent != CommandIntent.question;

  @override
  String toString() => 'OfflineCommand($intent, amount: $amount, qty: $qty, '
      'unit: $unit, name: $nameHint)';
}

// ── the words ──────────────────────────────────────────────────────
// Roman Urdu has no fixed spelling, so each of these carries the ways people
// actually type and say them. Written as sets rather than a regex because a
// shopkeeper adding "bech diya" to this list should not have to read a regex.

const _questionWords = {
  'kitna', 'kitni', 'kitne', 'kya', 'kia', 'kaun', 'kon', 'konsa', 'kaunsa',
  'kahan', 'kab', 'kyun', 'batao', 'bata', 'batayen', 'dikhao', 'dikha',
  'dikhaen', 'report', 'list', 'total', 'summary', 'hisab', 'hisaab',
  'how', 'what', 'which', 'who', 'when', 'where', 'show', 'tell',
};

const _expenseWords = {
  'kharcha', 'kharch', 'kharche', 'expense', 'bijli', 'bill', 'gas', 'pani',
  'kiraya', 'kiraye', 'rent', 'chai', 'petrol', 'diesel', 'tankhwah',
  'tankhuwah', 'salary', 'mazdoori', 'majdoori', 'repair', 'marammat',
  'internet', 'phone',
};

/// Goods went out.
const _sellWords = {
  'becha', 'bech', 'bechi', 'bechay', 'beche', 'bechdiya',
  'sale', 'sold', 'sell',
};

/// Goods came in.
const _buyWords = {
  'kharida', 'khareeda', 'kharidi', 'khareedi', 'kharid', 'khareed',
  'bought', 'buy', 'purchase',
};

/// Something changed hands. Which way is decided by the postposition.
const _giveWords = {
  'diye', 'diya', 'di', 'de', 'dia', 'dye', 'gave', 'paid', 'pay',
};

const _takeWords = {
  'liye', 'liya', 'li', 'lie', 'mile', 'mila', 'mili', 'aaye', 'aaya', 'aya',
  'wasool', 'wusool', 'jama', 'received', 'got', 'took',
};

/// Counted in these, so the number before it is a quantity and not rupees.
const _units = {
  'kilo', 'kg', 'gram', 'gm', 'g', 'litre', 'liter', 'ltr', 'l', 'ml',
  'pcs', 'piece', 'pieces', 'adad', 'packet', 'pkt', 'pack', 'bag', 'bori',
  'dozen', 'darjan', 'dzn', 'bottle', 'botal', 'btl', 'box', 'dabba',
  'meter', 'metre', 'gaz', 'yard', 'carton', 'peti',
};

/// Multiply the number before them.
const _multipliers = <String, int>{
  'sau': 100,
  'hazar': 1000, 'hazaar': 1000, 'hzr': 1000, 'k': 1000,
  'lakh': 100000, 'lac': 100000, 'lakhs': 100000,
  'crore': 10000000, 'karor': 10000000,
};

/// Only counted as numbers when a unit or multiplier follows.
///
/// "do" is both "two" and the tail of "kar do" / "bana do". Reading it as a
/// number everywhere turned "bill bana do" into a bill for two of something.
const _numberWords = <String, int>{
  'ek': 1, 'aik': 1, 'do': 2, 'teen': 3, 'tin': 3, 'char': 4, 'chaar': 4,
  'panch': 5, 'paanch': 5, 'che': 6, 'chay': 6, 'cheh': 6, 'saat': 7,
  'sat': 7, 'aath': 8, 'ath': 8, 'nau': 9, 'no': 9, 'das': 10, 'dus': 10,
  'bees': 20, 'bis': 20, 'pachas': 50, 'pachaas': 50,
};

/// Words that carry no meaning for this and only get in the way of a name.
const _noise = {
  'ka', 'ke', 'ki', 'ko', 'ne', 'se', 'par', 'pe', 'me', 'mein', 'main',
  'rupay', 'rupaye', 'rupee', 'rupees', 'rs', 'pkr', 'taka',
  'aur', 'or', 'plus', 'wala', 'wali', 'wale', 'hai', 'hain', 'tha', 'thi',
  'do', 'kar', 'karo', 'karen', 'karna', 'dena', 'likh', 'likho', 'likhdo',
  'bana', 'banao', 'banado', 'add', 'entry', 'please', 'zara', 'jee', 'ji',
  'the', 'a', 'an', 'of', 'for', 'to', 'from',
};

/// Urdu and Arabic keyboards produce their own digits, and a shopkeeper typing
/// on one is not typing something this should fail to read.
String _asciiDigits(String text) {
  final buffer = StringBuffer();
  for (final rune in text.runes) {
    if (rune >= 0x0660 && rune <= 0x0669) {
      buffer.writeCharCode(rune - 0x0660 + 0x30); // Arabic-Indic
    } else if (rune >= 0x06F0 && rune <= 0x06F9) {
      buffer.writeCharCode(rune - 0x06F0 + 0x30); // Extended (Urdu)
    } else {
      buffer.writeCharCode(rune);
    }
  }
  return buffer.toString();
}

/// A number found in the sentence, and what it turned out to mean.
class _Figure {
  _Figure(this.value);

  num value;
  bool isQty = false;
  String? unit;
}

/// Read a spoken or typed command.
///
/// Never throws and never guesses — an unreadable sentence comes back as
/// [CommandIntent.unknown].
OfflineCommand readCommand(String text) {
  final original = text.trim();
  if (original.isEmpty) {
    return OfflineCommand(intent: CommandIntent.unknown, original: original);
  }

  final words = _asciiDigits(original)
      .toLowerCase()
      // Dropped rather than turned into a space, or "5,000" splits into a five
      // and a nothing and the bill comes out at five rupees.
      .replaceAll(',', '')
      // Everything else that is not a letter or a digit is a separator, so
      // "5000/-" and "Ahmed:" read the same as without them.
      .replaceAll(RegExp(r'[^a-z0-9؀-ۿ\s.]'), ' ')
      .split(RegExp(r'\s+'))
      .where((w) => w.isNotEmpty)
      .toList();

  if (words.isEmpty) {
    return OfflineCommand(intent: CommandIntent.unknown, original: original);
  }

  final figures = _figuresIn(words);
  final intent = _intentOf(words, figures);

  // A question is answered from the shop's data, which is the server's job.
  // Pulling numbers out of it would only invite the caller to act on them.
  if (intent == CommandIntent.question || intent == CommandIntent.unknown) {
    return OfflineCommand(intent: intent, original: original);
  }

  final qty = figures.where((f) => f.isQty).firstOrNull;
  final money = figures.where((f) => !f.isQty).firstOrNull;

  return OfflineCommand(
    intent: intent,
    original: original,
    amount: money?.value,
    qty: qty?.value,
    unit: qty?.unit,
    nameHint: _nameIn(words),
  );
}

/// Every number in the sentence, with multipliers applied and quantities
/// marked by the unit that follows them.
List<_Figure> _figuresIn(List<String> words) {
  final found = <_Figure>[];

  for (var i = 0; i < words.length; i++) {
    final word = words[i];
    num? value = num.tryParse(word);

    // A number word only counts when a unit or multiplier follows it, so
    // "bana do" stays a verb and "do kilo" becomes two.
    if (value == null && _numberWords.containsKey(word)) {
      final next = i + 1 < words.length ? words[i + 1] : '';
      if (_units.contains(next) || _multipliers.containsKey(next)) {
        value = _numberWords[word];
      }
    }
    if (value == null) continue;

    final figure = _Figure(value);

    final next = i + 1 < words.length ? words[i + 1] : '';
    if (_multipliers.containsKey(next)) {
      figure.value = value * _multipliers[next]!;
      i++; // the multiplier is spent
      final after = i + 1 < words.length ? words[i + 1] : '';
      if (_units.contains(after)) {
        figure.isQty = true;
        figure.unit = after;
      }
    } else if (_units.contains(next)) {
      figure.isQty = true;
      figure.unit = next;
    }

    found.add(figure);
  }

  // Two plain numbers and no unit anywhere: the larger is the money and the
  // smaller is the count. "2 cheeni 500" is two bags at five hundred, never
  // five hundred bags at two rupees.
  final plain = found.where((f) => !f.isQty).toList();
  if (plain.length == 2 && found.every((f) => !f.isQty)) {
    final smaller = plain[0].value <= plain[1].value ? plain[0] : plain[1];
    if (smaller.value != plain[0].value || plain[0].value != plain[1].value) {
      smaller.isQty = true;
    }
  }

  return found;
}

CommandIntent _intentOf(List<String> words, List<_Figure> figures) {
  final set = words.toSet();

  // Asked first. "aaj kitna becha" is a question about sales, not a sale, and
  // reading it as one would open a half-filled bill nobody asked for.
  if (set.intersection(_questionWords).isNotEmpty) {
    return CommandIntent.question;
  }

  final hasGoods = figures.any((f) => f.isQty);
  final sells = set.intersection(_sellWords).isNotEmpty;
  final buys = set.intersection(_buyWords).isNotEmpty;
  final gives = set.intersection(_giveWords).isNotEmpty;
  final takes = set.intersection(_takeWords).isNotEmpty;

  // An expense word only decides it when nothing says goods moved — a shop
  // really does sell phone cards and light bulbs.
  if (set.intersection(_expenseWords).isNotEmpty &&
      !sells && !buys && !hasGoods) {
    return CommandIntent.expense;
  }

  if (sells) return CommandIntent.sale;
  if (buys) return CommandIntent.purchase;

  // Where the postpositions earn their keep. "ne" and "se" both put the other
  // person on the giving end, so the money is coming in. English carries the
  // same distinction in "from" and "to".
  final theyGave =
      set.contains('ne') || set.contains('se') || set.contains('from');
  final weGave = set.contains('ko') || set.contains('to');

  if (gives || takes) {
    if (takes && !gives) return CommandIntent.paymentIn;
    if (theyGave && !weGave) return CommandIntent.paymentIn;
    if (weGave) {
      // Goods named alongside means it is a bill, not a cash payment.
      return hasGoods ? CommandIntent.sale : CommandIntent.paymentOut;
    }
    // English marks the payer by putting them in front of the verb, the way
    // "ne" does: "Ahmed paid 5000" is Ahmed paying. Without a name in front
    // there is nobody to attribute it to and nothing to lean on.
    if (gives && _subjectBefore(words, _giveWords)) {
      return CommandIntent.paymentIn;
    }
    return CommandIntent.unknown;
  }

  // No verb at all, but a quantity and someone to give it to is a bill.
  if (hasGoods && weGave) return CommandIntent.sale;

  return CommandIntent.unknown;
}

/// Which of the shop's own names the sentence meant.
///
/// The phone already holds the shop's parties and items, so this matches
/// against the real list rather than trying to infer a name from the sentence.
/// "cheeni" becomes "Sugar 50kg Bag" because that is what the shop calls it,
/// which nothing working from the sentence alone could know.
///
/// Returns the index of the match, or null when nothing is close enough. Being
/// unsure is a result: the caller shows a picker, and the shopkeeper taps the
/// right one in a second. Billing the wrong customer costs a great deal more.
int? bestMatch(String hint, List<String> names) {
  final needle = hint.trim().toLowerCase();
  if (needle.isEmpty || names.isEmpty) return null;

  int? prefix, contains, word;

  for (var i = 0; i < names.length; i++) {
    final name = names[i].trim().toLowerCase();
    if (name.isEmpty) continue;

    if (name == needle) return i;
    prefix ??= name.startsWith(needle) ? i : null;
    contains ??= name.contains(needle) ? i : null;

    // "ahmad traders" said as "ahmad". Only whole words count, so "ali" does
    // not quietly match "Malik Ali Kirana" through the middle of a word.
    if (word == null && name.split(RegExp(r'\s+')).contains(needle)) {
      word = i;
    }
  }

  // An exact hit returns above. After that, a name that starts with what was
  // said beats one that merely has it somewhere inside.
  return prefix ?? word ?? contains;
}

/// Whether somebody is named in front of the verb.
///
/// English puts the payer there — "Ahmed paid 5000" — which is the same job
/// "ne" does in Urdu. A number or a filler word in front is not a person, so
/// it does not count.
bool _subjectBefore(List<String> words, Set<String> verbs) {
  final verb = words.indexWhere(verbs.contains);
  if (verb <= 0) return false;

  return words.sublist(0, verb).any(
        (word) =>
            !_noise.contains(word) &&
            num.tryParse(word) == null &&
            !_numberWords.containsKey(word) &&
            !_units.contains(word),
      );
}

/// The words most likely to be a name.
///
/// Whatever sits before "ne", "ko" or "se" is the person in almost every
/// sentence a shopkeeper says. Without one of those there is nothing reliable
/// to go on, so this returns null and lets the screen ask.
String? _nameIn(List<String> words) {
  const markers = {'ne', 'ko', 'se'};

  final marker = words.indexWhere(markers.contains);
  if (marker <= 0) return null;

  final name = words
      .sublist(0, marker)
      .where((w) => !_noise.contains(w))
      .where((w) => num.tryParse(w) == null)
      .where((w) => !_numberWords.containsKey(w))
      .where((w) => !_units.contains(w))
      .toList();

  if (name.isEmpty) return null;

  // Two words is a shop name — "Ahmad Traders". Beyond that it has stopped
  // being a name and started being the rest of the sentence.
  return name.take(2).join(' ');
}
