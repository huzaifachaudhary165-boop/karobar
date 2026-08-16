import 'package:flutter_test/flutter_test.dart';
import 'package:karobar/core/network/api_exception.dart';

/// Which failures throw away a shopkeeper's work, and which do not.
///
/// A refusal and a collapse look the same from the form — both are an
/// exception — and treating them the same is what loses a bill. A 422 will
/// fail identically tomorrow, so it belongs on screen. A 500 usually succeeds
/// a moment later: measured against the live deployment, three writes in six
/// came back `database_error` inside one minute and every one of them worked
/// on a retry.
///
/// Queueing those is safe because every queued row carries a `client_uuid` and
/// the server keys on it — the same bill pushed twice is applied once.
void main() {
  ApiException at(int status, {String code = 'error'}) =>
      ApiException(message: 'x', code: code, statusCode: status);

  group('the server fell over', () {
    test('a 500 is a fault, not a refusal', () {
      expect(at(500).isServerFault, isTrue);
      expect(at(502).isServerFault, isTrue);
      expect(at(503).isServerFault, isTrue);
      expect(at(504).isServerFault, isTrue);
    });

    test('a database error carries a 500 and is caught by status', () {
      // The code varies with whatever broke; the status is the reliable part.
      expect(at(500, code: 'database_error').isServerFault, isTrue);
    });
  });

  group('the server said no', () {
    test('a refusal is never treated as a fault', () {
      for (final status in [400, 401, 403, 404, 409, 422, 429]) {
        expect(at(status).isServerFault, isFalse, reason: '$status');
      }
    });

    test('rate limiting is a refusal, not a collapse', () {
      // Queueing a throttled write would push it again the moment the signal
      // allows, into the same limit.
      expect(at(429).isRateLimited, isTrue);
      expect(at(429).isServerFault, isFalse);
    });

    test('a validation failure stays on screen where it can be fixed', () {
      expect(at(422).isValidation, isTrue);
      expect(at(422).isServerFault, isFalse);
    });
  });

  group('no server at all', () {
    test('offline and a fault are different things', () {
      final offline = ApiException(message: 'x', code: 'offline');
      expect(offline.isOffline, isTrue);
      // No status, because nothing answered.
      expect(offline.isServerFault, isFalse);
    });

    test('a missing status is not read as a fault', () {
      // `statusCode` is null when the request never reached anything. Reading
      // that as a 500 would queue writes that were rejected before they left.
      expect(ApiException(message: 'x', code: 'timeout').isServerFault, isFalse);
    });
  });
}
