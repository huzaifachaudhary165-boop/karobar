import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/ai/offline_command.dart';

/// Reading a command with no signal.
///
/// Everything the shopkeeper asks for here already works offline — bills,
/// payments and expenses queue and go up later. Understanding the sentence was
/// the only part that needed the server, and this is that part.
///
/// The sentences are the ones people actually say at a counter, not tidied-up
/// English. Getting one of these backwards puts a real entry in a real shop's
/// books the wrong way round, so the cases that decide direction are the ones
/// worth being sure about.
void main() {
  group('which way the money went', () {
    // The whole reason this reads postpositions instead of keywords. Same
    // verb, opposite entries — a keyword list matching "diye" posts one of
    // these into the books backwards.
    test('"ne ... diye" is the customer paying us', () {
      final command = readCommand('Ahmed ne 5000 diye');
      expect(command.intent, CommandIntent.paymentIn);
      expect(command.amount, 5000);
    });

    test('"ko ... diye" is us paying out', () {
      final command = readCommand('Ahmed ko 5000 diye');
      expect(command.intent, CommandIntent.paymentOut);
      expect(command.amount, 5000);
    });

    test('"se ... liye" is money coming in', () {
      expect(readCommand('Ahmed se 2000 liye').intent, CommandIntent.paymentIn);
    });

    test('"wasool" is money coming in whichever way it is phrased', () {
      expect(readCommand('Ahmed se 3000 wasool').intent, CommandIntent.paymentIn);
      expect(readCommand('Bilal ne 1500 jama karaye').intent, CommandIntent.paymentIn);
    });

    test('English mixed in reads the same', () {
      expect(readCommand('Ahmed paid 5000').intent, isNot(CommandIntent.unknown));
      expect(readCommand('received 5000 from Ahmed').intent, CommandIntent.paymentIn);
    });
  });

  group('a bill', () {
    test('goods named alongside a customer is a sale, not a payment', () {
      final command = readCommand('Ahmed ko 2 kilo cheeni 500 ka de do');
      expect(command.intent, CommandIntent.sale);
      expect(command.qty, 2);
      expect(command.unit, 'kilo');
      expect(command.amount, 500);
    });

    test('the selling word alone is enough', () {
      expect(readCommand('Bilal ko becha 1200 ka').intent, CommandIntent.sale);
    });

    test('a quantity and a customer with no verb is still a bill', () {
      expect(readCommand('Ahmed ko 3 packet biscuit').intent, CommandIntent.sale);
    });

    test('buying is told apart from selling', () {
      expect(readCommand('supplier se 10 bori chawal kharida').intent,
          CommandIntent.purchase);
    });
  });

  group('numbers as they are actually said', () {
    test('hazaar and sau multiply', () {
      expect(readCommand('Ahmed ne 5 hazaar diye').amount, 5000);
      expect(readCommand('Ahmed ne 2 lakh diye').amount, 200000);
    });

    test('number words count when a unit or multiplier follows', () {
      expect(readCommand('Ahmed ko do kilo cheeni de do').qty, 2);
      expect(readCommand('Ahmed ne paanch hazaar diye').amount, 5000);
    });

    test('"do" in "bana do" is not two of something', () {
      // The trap this whole rule exists for: "do" is both "two" and the tail
      // of "kar do" and "bana do".
      final command = readCommand('Ahmed ka bill bana do');
      expect(command.qty, isNull);
    });

    test('commas and slashes in a figure are not lost', () {
      expect(readCommand('Ahmed ne 5,000 diye').amount, 5000);
    });

    test('Urdu keyboard digits are read', () {
      // A shopkeeper on an Urdu keyboard is not typing something unreadable.
      expect(readCommand('Ahmed ne ۵۰۰۰ diye').amount, 5000);
    });

    test('a unit tells a count apart from rupees', () {
      final command = readCommand('Ahmed ko 5 kilo aata 900 ka');
      expect(command.qty, 5);
      expect(command.amount, 900);
    });
  });

  group('who it is about', () {
    test('the name before the postposition is picked up', () {
      expect(readCommand('Ahmed ne 5000 diye').nameHint, 'ahmed');
    });

    test('a two-word shop name survives', () {
      expect(readCommand('Ahmad Traders ko 5000 diye').nameHint, 'ahmad traders');
    });

    test('filler words do not become the name', () {
      final command = readCommand('zara Ahmed ko 500 de do');
      expect(command.nameHint, 'ahmed');
    });

    test('no postposition means no guess', () {
      // Better to open the screen and let them choose than to bill the wrong
      // customer confidently.
      expect(readCommand('becha 500 ka').nameHint, isNull);
    });
  });

  group('questions go to the server', () {
    test('a question is recognised as one', () {
      expect(readCommand('aaj ki sale kitni hai').intent, CommandIntent.question);
      expect(readCommand('Ahmed ka hisab dikhao').intent, CommandIntent.question);
    });

    test('a question about selling is not a sale', () {
      // "aaj kitna becha" carries a selling word. Read as a sale it would open
      // a half-filled bill nobody asked for.
      expect(readCommand('aaj kitna becha').intent, CommandIntent.question);
    });

    test('and it says plainly that it needs a signal', () {
      expect(readCommand('aaj ki sale kitni hai').worksOffline, isFalse);
    });
  });

  group('expenses', () {
    test('a shop cost is not a payment to anybody', () {
      expect(readCommand('bijli ka bill 3000').intent, CommandIntent.expense);
      expect(readCommand('chai 200 ka kharcha').intent, CommandIntent.expense);
    });

    test('selling a light bulb is still a sale', () {
      // A shop really does sell the things on the expense list.
      final command = readCommand('Ahmed ko 2 pcs bulb becha 300 ka');
      expect(command.intent, CommandIntent.sale);
    });
  });

  group('when it does not know', () {
    test('it says so rather than guessing', () {
      expect(readCommand('salam').intent, CommandIntent.unknown);
      expect(readCommand('achha theek hai').intent, CommandIntent.unknown);
    });

    test('empty and whitespace are handled, not thrown on', () {
      expect(readCommand('').intent, CommandIntent.unknown);
      expect(readCommand('    ').intent, CommandIntent.unknown);
    });

    test('punctuation alone does not crash it', () {
      expect(() => readCommand('!!! ??? ...'), returnsNormally);
    });

    test('an unknown command is not offered as something to act on', () {
      expect(readCommand('salam').worksOffline, isFalse);
      expect(readCommand('salam').isUnderstood, isFalse);
    });
  });

  group('matching against the shop\'s own names', () {
    // The reason no model is needed for this half: the phone already holds the
    // shop's parties and items, and the real list beats anything inferred from
    // the sentence.
    const parties = [
      'Ahmad Traders',
      'Ahmed Ali',
      'Malik Ali Kirana',
      'Bilal Store',
    ];

    test('an exact name wins', () {
      expect(bestMatch('Ahmed Ali', parties), 1);
    });

    test('the first word of a shop name finds it', () {
      expect(bestMatch('ahmad', parties), 0);
    });

    test('a whole word inside the name counts', () {
      expect(bestMatch('kirana', parties), 2);
    });

    test('a word is not matched through the middle of another', () {
      // "ali" must not quietly become "Malik Ali Kirana" when "Ahmed Ali" is
      // the one they meant. Word matching, not substring.
      expect(bestMatch('ali', parties), 1);
    });

    test('a name the shop does not have comes back empty', () {
      // The screen then asks. Billing the nearest-looking customer would be
      // found weeks later, in somebody else's ledger.
      expect(bestMatch('Zubair', parties), isNull);
    });

    test('an empty hint or an empty list is not a match', () {
      expect(bestMatch('', parties), isNull);
      expect(bestMatch('Ahmed', const []), isNull);
    });

    test('case and spacing do not matter', () {
      expect(bestMatch('  BILAL  ', parties), 3);
    });
  });

  group('what can be done without a signal', () {
    test('bills, payments and expenses all can', () {
      for (final sentence in [
        'Ahmed ne 5000 diye',
        'Ahmed ko 5000 diye',
        'Ahmed ko 2 kilo cheeni 500 ka de do',
        'bijli ka bill 3000',
      ]) {
        expect(readCommand(sentence).worksOffline, isTrue, reason: sentence);
      }
    });

    test('only a question needs one', () {
      expect(readCommand('aaj ki sale kitni hai').worksOffline, isFalse);
    });
  });
}
