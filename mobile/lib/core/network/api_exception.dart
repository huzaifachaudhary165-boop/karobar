import 'package:dio/dio.dart';

/// A failure the UI can show verbatim.
///
/// The backend always answers with
/// `{"error": {"code", "message", "details"}, "request_id"}`, so this parses that
/// envelope and falls back to a human sentence for transport-level problems.
class ApiException implements Exception {
  ApiException({
    required this.message,
    this.code = 'error',
    this.statusCode,
    this.details = const {},
    this.requestId,
  });

  final String message;
  final String code;
  final int? statusCode;
  final Map<String, dynamic> details;
  final String? requestId;

  bool get isUnauthorized => statusCode == 401 || code == 'unauthenticated';
  bool get isForbidden => statusCode == 403 || code == 'forbidden';
  bool get isNotFound => statusCode == 404 || code == 'not_found';
  bool get isConflict => statusCode == 409;
  bool get isValidation => code == 'validation_error' || statusCode == 422;
  bool get isRateLimited => statusCode == 429;
  bool get isOffline => code == 'offline' || code == 'timeout';
  bool get isServerError => (statusCode ?? 0) >= 500;
  bool get isAiUnavailable => code.startsWith('ai_');

  /// Field-level messages from a 422, keyed by field name.
  Map<String, String> get fieldErrors {
    final fields = details['fields'];
    if (fields is Map) {
      return fields.map((key, value) => MapEntry(key.toString(), value.toString()));
    }
    return const {};
  }

  factory ApiException.fromDio(DioException error) {
    final response = error.response;
    final data = response?.data;

    if (data is Map && data['error'] is Map) {
      final payload = Map<String, dynamic>.from(data['error'] as Map);
      return ApiException(
        message: (payload['message'] ?? 'Something went wrong.').toString(),
        code: (payload['code'] ?? 'error').toString(),
        statusCode: response?.statusCode,
        details: Map<String, dynamic>.from(payload['details'] as Map? ?? {}),
        requestId: data['request_id']?.toString(),
      );
    }

    final (message, code) = switch (error.type) {
      DioExceptionType.connectionTimeout ||
      DioExceptionType.sendTimeout ||
      DioExceptionType.receiveTimeout =>
        ('The server is taking too long to respond. Please try again.', 'timeout'),
      DioExceptionType.connectionError => (
          'Cannot reach the server. Check your internet connection.',
          'offline',
        ),
      DioExceptionType.cancel => ('Request cancelled.', 'cancelled'),
      DioExceptionType.badCertificate => ('The server certificate is not trusted.', 'bad_cert'),
      // `unknown` with nothing to show for it is what Dio reports when the
      // request never left, or when something threw inside the client itself.
      // Saying only "something went wrong" leaves nobody anything to act on or
      // report, so the underlying cause is carried through — it is the only
      // description that exists.
      DioExceptionType.unknown when response == null => (
          'The request could not be sent. '
              '${_cause(error)}Check your connection and try again.',
          'request_failed',
        ),
      _ => _fromStatus(response?.statusCode),
    };

    return ApiException(message: message, code: code, statusCode: response?.statusCode);
  }

  static String _cause(DioException error) {
    final detail = (error.error ?? error.message)?.toString().trim();
    if (detail == null || detail.isEmpty) return '';
    return '(${detail.length > 140 ? '${detail.substring(0, 140)}…' : detail}) ';
  }

  static (String, String) _fromStatus(int? status) {
    if (status == null) return ('Something went wrong.', 'error');
    return switch (status) {
      401 => ('Please sign in again.', 'unauthenticated'),
      403 => ('You do not have permission to do that.', 'forbidden'),
      404 => ('Not found.', 'not_found'),
      429 => ('Too many requests. Please slow down.', 'rate_limited'),
      >= 500 => ('The server had a problem. Please try again shortly.', 'server_error'),
      _ => ('Something went wrong.', 'error'),
    };
  }

  factory ApiException.offline() => ApiException(
        message: 'You are offline. Changes will sync when you reconnect.',
        code: 'offline',
      );

  @override
  String toString() => message;
}
