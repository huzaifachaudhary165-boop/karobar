import 'package:flutter/widgets.dart';

/// Lightweight three-language dictionary (English, Roman Urdu, Roman Hindi).
///
/// Deliberately map-based rather than ARB + codegen: the surface is small, the
/// two non-English locales are Roman transliterations that shop owners actually
/// type, and a missing key falls back to English instead of failing the build.
class Strings {
  const Strings(this.locale);

  final String locale;

  static Strings of(BuildContext context) =>
      Strings(Localizations.localeOf(context).languageCode);

  String get(String key) =>
      _table[locale]?[key] ?? _table['en']![key] ?? key;

  String call(String key) => get(key);

  /// Translations keyed by the **English source text**, not by an invented key.
  ///
  /// That choice matters: the code keeps reading `t('Save shop details')`, so a
  /// screen stays legible, a typo cannot silently point at nothing, and anything
  /// not translated yet shows in English rather than as a raw key.
  ///
  /// Roman Urdu and Roman Hindi are written the way shopkeepers speak, not as
  /// literary translation — "Rehne do" beats "Mansookh karein" on a button
  /// somebody taps forty times a day.
  static const Map<String, (String ur, String hi)> _text = {
    'Save': ('Save karo', 'Save karein'),
    'Cancel': ('Rehne do', 'Rehne dein'),
    'Delete': ('Delete karo', 'Delete karein'),
    'Remove': ('Hatao', 'Hataayein'),
    'Change': ('Badlo', 'Badlein'),
    'Retry': ('Dobara koshish', 'Phir se'),
    'Refresh': ('Taza karo', 'Taaza karein'),
    'Continue': ('Aage barho', 'Aage badhein'),
    'Keep it': ('Rehne do', 'Rehne dein'),
    'Keep them': ('Rehne do', 'Rehne dein'),
    'Not now': ('Abhi nahi', 'Abhi nahin'),
    'View': ('Dekho', 'Dekhein'),
    'Print': ('Print karo', 'Print karein'),
    'Connect': ('Jodo', 'Jodein'),
    'Adjust': ('Theek karo', 'Theek karein'),
    'Amount': ('Raqam', 'Raqam'),
    'Notes': ('Note', 'Note'),
    'Items': ('Cheezain', 'Saamaan'),
    'Party': ('Party', 'Party'),
    'Invoice': ('Bill', 'Bill'),
    'Payments': ('Payments', 'Payments'),
    'Alerts': ('Ittelaat', 'Soochnaayein'),
    'Settings': ('Settings', 'Settings'),
    'Team': ('Team', 'Team'),
    'Reports': ('Reports', 'Reports'),
    'Language': ('Zubaan', 'Bhasha'),
    'Appearance': ('Look', 'Look'),
    'Your data': ('Aapka data', 'Aapka data'),
    'Assistant': ('Madadgar', 'Sahayak'),
    'Add item': ('Cheez daalo', 'Saamaan jodein'),
    'Add new': ('Naya daalo', 'Naya jodein'),
    'Add someone': ('Banda daalo', 'Vyakti jodein'),
    'Add new item': ('Nayi cheez daalo', 'Naya saamaan jodein'),
    'Welcome back': ('Khush aamdeed', 'Swagat hai'),
    'Sign in to your shop': ('Apni dukan mein aayein', 'Apni dukan mein aayein'),
    'Email or phone number': ('Email ya phone number', 'Email ya phone number'),
    'Password': ('Password', 'Password'),
    'Verification code': ('Tasdeeq code', 'Verification code'),
    'New here?': ('Naye hain?', 'Naye hain?'),
    'Create your shop account': ('Apni dukan ka account banayein', 'Apni dukan ka account banayein'),
    'Create your account': ('Apna account banayein', 'Apna account banayein'),
    'Create my shop': ('Meri dukan banao', 'Meri dukan banayein'),
    'Business type': ('Karobar ki qism', 'Vyapar ka prakar'),
    'Country': ('Mulk', 'Desh'),
    'Phone number': ('Phone number', 'Phone number'),
    'Email (optional)': ('Email (marzi se)', 'Email (vaikalpik)'),
    'At least 8 characters, with a number': ('Kam az kam 8 harf, ek number ke saath', 'Kam se kam 8 akshar, ek number ke saath'),
    'Set up your shop': ('Apni dukan taiyar karein', 'Apni dukan taiyaar karein'),
    'Add your first customer': ('Pehla customer daalein', 'Pehla customer jodein'),
    'Add an item you sell': ('Jo bechte hain wo daalein', 'Jo bechte hain wo jodein'),
    'Make your first bill': ('Pehla bill banayein', 'Pehla bill banayein'),
    'This month': ('Is mahine', 'Is mahine'),
    'Last month': ('Pichhle mahine', 'Pichhle mahine'),
    'This quarter': ('Is teen mahine', 'Is timahi'),
    'This year': ('Is saal', 'Is saal'),
    'Financial year': ('Maali saal', 'Vittiya varsh'),
    'Net profit': ('Saaf nafa', 'Shuddh laabh'),
    'Total outstanding': ('Kul baqaya', 'Kul bakaya'),
    'Customer': ('Customer', 'Customer'),
    'Supplier': ('Supplier', 'Supplier'),
    'Name *': ('Naam *', 'Naam *'),
    'Phone': ('Phone', 'Phone'),
    'Email': ('Email', 'Email'),
    'Address': ('Pata', 'Pata'),
    'Credit limit': ('Udhaar ki hadd', 'Udhaar ki seema'),
    'Opening balance': ('Purana hisaab', 'Purana hisaab'),
    'New bill': ('Naya bill', 'Naya bill'),
    'Record payment': ('Payment likho', 'Payment darj karein'),
    'Total business': ('Kul karobar', 'Kul vyapar'),
    'Call': ('Call karo', 'Call karein'),
    'WhatsApp': ('WhatsApp', 'WhatsApp'),
    'No transactions yet.': ('Abhi koi len den nahi.', 'Abhi koi len-den nahin.'),
    'Search by name or phone': ('Naam ya phone se dhoondein', 'Naam ya phone se dhoondein'),
    'Used for WhatsApp reminders and invoice sharing': ('WhatsApp reminder aur bill bhejne ke liye', 'WhatsApp reminder aur bill bhejne ke liye'),
    'You will be warned when their dues cross this': ('Isse zyada udhaar hone par aapko batayenge', 'Isse zyada udhaar hone par bata denge'),
    'Barcode': ('Barcode', 'Barcode'),
    'Cost price': ('Kharid ka rate', 'Kharid ka rate'),
    'Current stock': ('Maujooda stock', 'Maujooda stock'),
    'Adjust stock': ('Stock theek karo', 'Stock theek karein'),
    'Apply adjustment': ('Laagu karo', 'Laagu karein'),
    'Alert below': ('Isse kam par batao', 'Isse kam par batayein'),
    'Damaged / stock count / wastage': ('Toot gaya / ginti / zaya', 'Toot gaya / ginti / barbaad'),
    'Delete this item?': ('Ye cheez delete karein?', 'Ye saamaan delete karein?'),
    'Scan a barcode': ('Barcode scan karo', 'Barcode scan karein'),
    'New barcode': ('Naya barcode', 'Naya barcode'),
    'Search by name, SKU or barcode': ('Naam, SKU ya barcode se dhoondein', 'Naam, SKU ya barcode se dhoondein'),
    'Discount': ('Riayat', 'Chhoot'),
    'Amount received': ('Milne wali raqam', 'Prapt raqam'),
    'No items yet': ('Abhi koi cheez nahi', 'Abhi kuch nahin'),
    'Add the first item': ('Pehli cheez daalein', 'Pehla saamaan jodein'),
    'Notes (optional)': ('Note (marzi se)', 'Note (vaikalpik)'),
    'Full': ('Poora', 'Poora'),
    'Low': ('Kam', 'Kam'),
    'Quotation': ('Quotation', 'Quotation'),
    'Print receipt': ('Rasid print karo', 'Rasid print karein'),
    'Send on WhatsApp': ('WhatsApp par bhejo', 'WhatsApp par bhejein'),
    'Share summary': ('Tafseel bhejo', 'Vivaran bhejein'),
    'Cancel invoice': ('Bill cancel karo', 'Bill cancel karein'),
    'Cancel this invoice?': ('Ye bill cancel karein?', 'Ye bill cancel karein?'),
    'Search by number or customer': ('Number ya customer se dhoondein', 'Number ya customer se dhoondein'),
    'New expense': ('Naya kharcha', 'Naya kharch'),
    'Record expense': ('Kharcha likho', 'Kharch darj karein'),
    'All expenses': ('Saare kharche', 'Sabhi kharch'),
    'Delete this expense?': ('Ye kharcha delete karein?', 'Ye kharch delete karein?'),
    'Amount *': ('Raqam *', 'Raqam *'),
    'Category': ('Qism', 'Shreni'),
    'Paid with': ('Kis se diya', 'Kis se diya'),
    'Paid to (optional)': ('Kis ko diya (marzi se)', 'Kise diya (vaikalpik)'),
    'What was it for? *': ('Kis cheez ka tha? *', 'Kis cheez ka tha? *'),
    'How can I help?': ('Kya madad karun?', 'Kya madad karun?'),
    'New chat': ('Nayi baat', 'Nayi baat'),
    'Scan a bill': ('Bill scan karo', 'Bill scan karein'),
    'Photograph a supplier bill': ('Supplier ka bill photo karein', 'Supplier ka bill photo karein'),
    'Choose from gallery': ('Gallery se chunein', 'Gallery se chunein'),
    'Start over': ('Dobara shuru', 'Phir se shuru'),
    'Purchase bill': ('Kharid ka bill', 'Kharid ka bill'),
    'Expense': ('Kharcha', 'Kharch'),
    'Save as': ('Kis tarah save karein', 'Kis roop mein save karein'),
    'For the best results': ('Behtar nateeje ke liye', 'Behtar natije ke liye'),
    'Add to my shop': ('Meri dukan mein daalo', 'Meri dukan mein jodein'),
    'Change role': ('Kaam badlo', 'Bhoomika badlein'),
    'Not joined yet': ('Abhi shamil nahi', 'Abhi shaamil nahin'),
    'Paused': ('Roka hua', 'Roka hua'),
    '(you)': ('(aap)', '(aap)'),
    'Restore': ('Wapas laao', 'Wapas laayein'),
    'Restore this backup?': ('Ye backup wapas laayein?', 'Ye backup wapas laayein?'),
    'Delete all transactions?': ('Saare len den delete karein?', 'Sabhi len-den delete karein?'),
    'Which period?': ('Kaunsa arsa?', 'Kaunsi avadhi?'),
    'Printer': ('Printer', 'Printer'),
    'Paper width': ('Kagaz ki chaurai', 'Kaagaz ki chaudai'),
    'Print labels': ('Label print karo', 'Label print karein'),
    'How many?': ('Kitne?', 'Kitne?'),
    'Mark all read': ('Sab parha hua', 'Sab padha hua'),
  };

  /// Looks a sentence up by its English text.
  String t(String english) {
    final entry = _text[english];
    if (entry == null) return english;
    return switch (locale) {
      'ur' => entry.$1,
      'hi' => entry.$2,
      _ => english,
    };
  }


  static const supported = ['en', 'ur', 'hi'];

  /// Labelled the way a shopkeeper would recognise themselves.
  ///
  /// The old labels showed اردو / हिन्दी in native script while claiming to be
  /// Roman, so the person who actually types "Ahmed ka bill banao" could not
  /// tell which one was theirs. The assistant understands native script too —
  /// it replies in whatever it is written to — but the *choice* here is about
  /// how the app's own labels read.
  static const languageNames = {
    'en': 'English',
    'ur': 'Roman Urdu',
    'hi': 'Roman Hindi',
  };

  /// One line of each, so the choice is made by recognition rather than by
  /// decoding a language name.
  static const languageSamples = {
    'en': 'Make a bill for Ahmed',
    'ur': 'Ahmed ka bill banao',
    'hi': 'Ahmed ka bill banaao',
  };

  static const Map<String, Map<String, String>> _table = {
    'en': {
      // navigation
      'home': 'Home',
      'parties': 'Parties',
      'items': 'Items',
      'invoices': 'Invoices',
      'reports': 'Reports',
      'assistant': 'Assistant',
      'settings': 'Settings',
      // dashboard
      'todays_sales': "Today's sales",
      'sales': 'Sales',
      'purchases': 'Purchases',
      'expenses': 'Expenses',
      'profit': 'Profit',
      'to_collect': 'To collect',
      'to_pay': 'To pay',
      'cash_in_hand': 'Cash in hand',
      'stock_value': 'Stock value',
      'quick_actions': 'Quick actions',
      'recent_activity': 'Recent activity',
      'needs_attention': 'Needs attention',
      // actions
      'new_sale': 'New sale',
      'new_purchase': 'New purchase',
      'add_customer': 'Add customer',
      'calculator': 'Calculator',
      'add_item': 'Add item',
      'receive_payment': 'Receive payment',
      'add_expense': 'Add expense',
      'scan_bill': 'Scan bill',
      'save': 'Save',
      'cancel': 'Cancel',
      'delete': 'Delete',
      'edit': 'Edit',
      'share': 'Share',
      'retry': 'Retry',
      'search': 'Search',
      'done': 'Done',
      // entities
      'customer': 'Customer',
      'supplier': 'Supplier',
      'balance': 'Balance',
      'owes_you': 'Owes you',
      'you_owe': 'You owe',
      'settled': 'Settled',
      'in_stock': 'In stock',
      'low_stock': 'Low stock',
      'out_of_stock': 'Out of stock',
      'total': 'Total',
      'paid': 'Paid',
      'due': 'Due',
      // states
      'loading': 'Loading…',
      'no_data': 'Nothing here yet',
      'offline': 'You are offline',
      'sign_in': 'Sign in',
      'sign_out': 'Sign out',
      'ask_anything': 'Ask anything about your shop…',
    },
    'ur': {
      'home': 'Home',
      'parties': 'Customers',
      'items': 'Items',
      'invoices': 'Bills',
      'reports': 'Reports',
      'assistant': 'Assistant',
      'settings': 'Settings',
      'todays_sales': 'Aaj ki sale',
      'sales': 'Sale',
      'purchases': 'Kharid',
      'expenses': 'Kharcha',
      'profit': 'Munafa',
      'to_collect': 'Wasooli baqi',
      'to_pay': 'Adaigi baqi',
      'cash_in_hand': 'Cash mojood',
      'stock_value': 'Stock ki qeemat',
      'quick_actions': 'Foran karein',
      'recent_activity': 'Haal ki entries',
      'needs_attention': 'Tawajjo darkaar',
      'new_sale': 'Nayi sale',
      'new_purchase': 'Nayi kharid',
      'add_customer': 'Customer add karein',
      'calculator': 'Calculator',
      'add_item': 'Item add karein',
      'receive_payment': 'Payment wasool karein',
      'add_expense': 'Kharcha likhein',
      'scan_bill': 'Bill scan karein',
      'save': 'Mehfooz karein',
      'cancel': 'Mansookh',
      'delete': 'Hazf karein',
      'edit': 'Tabdeeli',
      'share': 'Bhejein',
      'retry': 'Dobara koshish',
      'search': 'Talash',
      'done': 'Ho gaya',
      'customer': 'Customer',
      'supplier': 'Supplier',
      'balance': 'Baqi',
      'owes_you': 'Aap ko dene hain',
      'you_owe': 'Aap ne dene hain',
      'settled': 'Hisab barabar',
      'in_stock': 'Stock mein',
      'low_stock': 'Stock kam',
      'out_of_stock': 'Stock khatam',
      'total': 'Total',
      'paid': 'Ada shuda',
      'due': 'Baqi',
      'loading': 'Load ho raha hai…',
      'no_data': 'Abhi kuch nahi hai',
      'offline': 'Aap offline hain',
      'sign_in': 'Dakhil hon',
      'sign_out': 'Bahar niklein',
      'ask_anything': 'Apni dukan ke bare mein kuch bhi poochein…',
    },
    'hi': {
      'home': 'Home',
      'parties': 'Customers',
      'items': 'Items',
      'invoices': 'Bills',
      'reports': 'Reports',
      'assistant': 'Assistant',
      'settings': 'Settings',
      'todays_sales': 'Aaj ki bikri',
      'sales': 'Bikri',
      'purchases': 'Kharid',
      'expenses': 'Kharcha',
      'profit': 'Munafa',
      'to_collect': 'Vasooli baki',
      'to_pay': 'Bhugtan baki',
      'cash_in_hand': 'Cash mojood',
      'stock_value': 'Stock ki keemat',
      'quick_actions': 'Turant karein',
      'recent_activity': 'Haal ki entries',
      'needs_attention': 'Dhyan dein',
      'new_sale': 'Nayi bikri',
      'new_purchase': 'Nayi kharid',
      'add_customer': 'Customer jodein',
      'calculator': 'Calculator',
      'add_item': 'Item jodein',
      'receive_payment': 'Payment lein',
      'add_expense': 'Kharcha likhein',
      'scan_bill': 'Bill scan karein',
      'save': 'Save karein',
      'cancel': 'Radd karein',
      'delete': 'Hataayein',
      'edit': 'Badlein',
      'share': 'Bhejein',
      'retry': 'Phir koshish',
      'search': 'Khojein',
      'done': 'Ho gaya',
      'customer': 'Customer',
      'supplier': 'Supplier',
      'balance': 'Baki',
      'owes_you': 'Aapko dene hain',
      'you_owe': 'Aapne dene hain',
      'settled': 'Hisab barabar',
      'in_stock': 'Stock mein',
      'low_stock': 'Stock kam',
      'out_of_stock': 'Stock khatam',
      'total': 'Total',
      'paid': 'Bhugtan',
      'due': 'Baki',
      'loading': 'Load ho raha hai…',
      'no_data': 'Abhi kuch nahi hai',
      'offline': 'Aap offline hain',
      'sign_in': 'Login karein',
      'sign_out': 'Logout',
      'ask_anything': 'Apni dukan ke bare mein kuch bhi poochein…',
    },
  };
}

extension StringsX on BuildContext {
  Strings get s => Strings.of(this);

  /// Key-based lookup, for the original short labels.
  String tr(String key) => Strings.of(this).get(key);

  /// Source-text lookup: `context.t('Print receipt')`.
  String t(String english) => Strings.of(this).t(english);
}
