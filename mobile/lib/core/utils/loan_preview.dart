import 'dart:math' as math;

/// The monthly instalment, worked out on the phone so the figure appears while
/// the loan is still being typed.
///
/// The server remains the authority — this only has to *agree* with it. Two
/// implementations of one formula is a real risk: a shopkeeper who is shown
/// 23,536 and then saves a loan of 23,540 has no reason to trust either number
/// again. `loan_preview_test.dart` pins this to the same figures the backend's
/// own tests use, so a change to one that is not made to the other fails here.
///
/// Returns null when there is not enough to calculate with, which is most of
/// the time a form is being filled in.
double? previewInstalment({
  required num? principal,
  required int? months,
  num rate = 0,
  String interestType = 'reducing',
}) {
  if (principal == null || principal <= 0 || months == null || months <= 0) {
    return null;
  }

  // No rate means no interest, whatever the type says. A shop borrowing from
  // family is the common case, not the exception.
  if (rate <= 0 || interestType == 'none') {
    return _round(principal / months);
  }

  if (interestType == 'flat') {
    // Charged on the full amount for the whole term, so it never reduces —
    // which is why "12% flat" costs far more than 12% and the two must not be
    // shown as the same offer.
    final interest = principal * rate / 100 * months / 12;
    return _round((principal + interest) / months);
  }

  final monthly = rate / 100 / 12;
  final growth = math.pow(1 + monthly, months);
  return _round(principal * monthly * growth / (growth - 1));
}

/// What the whole loan will have cost in interest by the end.
///
/// Worked out by walking the repayment plan rather than as
/// `instalment × months − principal`. The instalment is a rounded figure, so
/// multiplying it back out overstates the cost by the accumulated rounding —
/// 5,166.67 × 24 comes to 124,000.08 on a loan that really costs 124,000. A
/// lender absorbs that in the final instalment and so does the server, so this
/// does too. The number shown here then equals the sum of the schedule the
/// borrower sees once the loan is saved.
num? previewTotalInterest({
  required num? principal,
  required int? months,
  num rate = 0,
  String interestType = 'reducing',
}) {
  final instalment = previewInstalment(
    principal: principal,
    months: months,
    rate: rate,
    interestType: interestType,
  );
  if (instalment == null) return null;
  if (rate <= 0 || interestType == 'none') return 0;

  if (interestType == 'flat') {
    // Fixed at the outset and does not depend on the instalment at all.
    return _round(principal! * rate / 100 * months! / 12);
  }

  final monthly = rate / 100 / 12;
  var balance = _round(principal!);
  num total = 0;

  for (var i = 1; i <= months!; i++) {
    final interest = _round(balance * monthly);
    var repaid = _round(instalment - interest);
    // The last instalment clears whatever is left, however the rounding fell.
    if (i == months || repaid > balance) repaid = balance;

    total += interest;
    balance = _round(balance - repaid);
    if (balance <= 0) break;
  }
  return _round(total);
}

/// Two decimal places, away from zero on a half — the same rule the server's
/// money helper uses, so the two never round a half-paisa apart.
double _round(num value) => (value * 100).round() / 100;
