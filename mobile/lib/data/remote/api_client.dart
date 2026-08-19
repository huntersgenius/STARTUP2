import 'package:dio/dio.dart';

import '../../core/constants.dart';

/// Thin transport over the backend.
///
/// Every method distinguishes three outcomes, because the sync engine treats
/// them completely differently:
///
/// - success
/// - a **transient** failure (offline, timeout, 5xx) → retry later, keep the
///   outbox row
/// - a **permanent** failure (4xx that is not 401) → the operation will never
///   succeed as written; surface it rather than retrying forever
class ApiException implements Exception {
  ApiException(this.message, {required this.transient, this.statusCode});

  final String message;
  final bool transient;
  final int? statusCode;

  @override
  String toString() =>
      'ApiException($statusCode, transient: $transient): $message';
}

class TokenPair {
  const TokenPair({required this.accessToken, required this.refreshToken});
  final String accessToken;
  final String refreshToken;
}

class ApiClient {
  ApiClient({required Dio dio}) : _dio = dio;

  final Dio _dio;
  String? _accessToken;

  void setAccessToken(String? token) => _accessToken = token;

  Options get _options => Options(
        headers: <String, String>{
          if (_accessToken != null) 'Authorization': 'Bearer $_accessToken',
        },
      );

  static ApiException _wrap(DioException e) {
    final int? status = e.response?.statusCode;
    final bool transient = status == null || status >= 500 || status == 429;
    final String message = e.response?.data is Map
        ? ((e.response!.data as Map)['detail']?.toString() ??
            e.message ??
            'request failed')
        : (e.message ?? 'request failed');
    return ApiException(message, transient: transient, statusCode: status);
  }

  Future<TokenPair> login(String email, String password) async {
    try {
      final Response<dynamic> response = await _dio.post<dynamic>(
        ApiRoutes.login,
        data: <String, String>{'email': email, 'password': password},
      );
      final Map<String, dynamic> body =
          (response.data as Map).cast<String, dynamic>();
      return TokenPair(
        accessToken: body['access_token'] as String,
        refreshToken: body['refresh_token'] as String,
      );
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<String> refresh(String refreshToken) async {
    try {
      final Response<dynamic> response = await _dio.post<dynamic>(
        ApiRoutes.refresh,
        data: <String, String>{'refresh_token': refreshToken},
      );
      return ((response.data as Map).cast<String, dynamic>())['access_token']
          as String;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// Push a batch of outbox operations. Returns the per-operation results.
  Future<List<Map<String, dynamic>>> sync({
    required String deviceId,
    required List<Map<String, dynamic>> operations,
  }) async {
    try {
      final Response<dynamic> response = await _dio.post<dynamic>(
        ApiRoutes.sync,
        data: <String, dynamic>{
          'device_id': deviceId,
          'operations': operations
        },
        options: _options,
      );
      final Map<String, dynamic> body =
          (response.data as Map).cast<String, dynamic>();
      return (body['results'] as List)
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<Map<String, dynamic>> analyze(String consultationId,
      {bool offline = false}) async {
    try {
      final Response<dynamic> response = await _dio.post<dynamic>(
        ApiRoutes.analyze(consultationId),
        data: <String, dynamic>{'offline': offline},
        options: _options,
      );
      _assertDisclaimerPresent(response);
      return (response.data as Map).cast<String, dynamic>();
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<Map<String, dynamic>> recordDecision(
    String suggestionId, {
    required String action,
    String? finalText,
    String? reason,
  }) async {
    try {
      final Response<dynamic> response = await _dio.post<dynamic>(
        ApiRoutes.decision(suggestionId),
        data: <String, dynamic>{
          'action': action,
          if (finalText != null) 'final_text': finalText,
          if (reason != null) 'reason': reason,
        },
        options: _options,
      );
      return (response.data as Map).cast<String, dynamic>();
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// A response carrying a suggestion must carry the disclaimer header.
  ///
  /// If a future server change drops it, the app refuses the response instead
  /// of rendering clinical content without the clinician-in-the-loop notice.
  void _assertDisclaimerPresent(Response<dynamic> response) {
    final String? header = response.headers.value(kDisclaimerHeader);
    if (header == null || !header.contains('clinician-review-required')) {
      throw ApiException(
        'server response is missing the clinical disclaimer header',
        transient: false,
        statusCode: response.statusCode,
      );
    }
  }
}
