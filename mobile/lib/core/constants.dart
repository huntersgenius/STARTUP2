/// Values that must match the backend contract exactly.
library;

class ApiRoutes {
  static const String login = '/api/v1/auth/login';
  static const String refresh = '/api/v1/auth/refresh';
  static const String me = '/api/v1/auth/me';
  static const String patients = '/api/v1/patients';
  static const String consultations = '/api/v1/consultations';
  static const String sync = '/api/v1/sync';

  static String analyze(String consultationId) =>
      '/api/v1/consultations/$consultationId/analyze';
  static String decision(String suggestionId) =>
      '/api/v1/suggestions/$suggestionId/decision';
}

/// Header the backend sets on every response. Its presence is asserted before
/// any suggestion is rendered — a build that drops the disclaimer must fail
/// loudly rather than quietly ship a screen without it.
const String kDisclaimerHeader = 'x-clinical-disclaimer';
const String kDisclaimerToken = 'not-a-diagnosis; clinician-review-required';

/// Below this confidence the app shows follow-up questions instead of a
/// ranked list. Mirrors `min_confidence_to_rank` on the server.
const double kMinConfidenceToRank = 0.4;

/// How long the outbox waits before retrying, per attempt.
const List<Duration> kRetryBackoff = <Duration>[
  Duration(seconds: 5),
  Duration(seconds: 30),
  Duration(minutes: 2),
  Duration(minutes: 10),
  Duration(hours: 1),
];
