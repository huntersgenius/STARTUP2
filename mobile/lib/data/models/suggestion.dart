import 'dart:convert';

/// Client-side mirror of the backend's `ClinicalSuggestion` schema.
///
/// Parsing is deliberately defensive: a field the server adds later must not
/// crash a tablet in a village that has not been updated in six months.
class Differential {
  const Differential({
    required this.condition,
    required this.confidence,
    required this.why,
    this.icd10,
    this.citations = const <String>[],
    this.redFlags = const <String>[],
  });

  final String condition;
  final String? icd10;
  final double confidence;
  final String why;
  final List<String> citations;
  final List<String> redFlags;

  factory Differential.fromJson(Map<String, dynamic> json) => Differential(
        condition: (json['condition'] ?? '').toString(),
        icd10: json['icd10']?.toString(),
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
        why: (json['why'] ?? '').toString(),
        citations: _stringList(json['citations']),
        redFlags: _stringList(json['red_flags']),
      );
}

class RedFlagBanner {
  const RedFlagBanner({
    required this.code,
    required this.urgency,
    required this.message,
    required this.referTo,
  });

  final String code;
  final String urgency;
  final String message;
  final String referTo;

  bool get isImmediate => urgency == 'immediate';

  factory RedFlagBanner.fromJson(Map<String, dynamic> json) => RedFlagBanner(
        code: (json['code'] ?? '').toString(),
        urgency: (json['urgency'] ?? 'urgent').toString(),
        message: (json['message'] ?? '').toString(),
        referTo: (json['refer_to'] ?? '').toString(),
      );
}

class TreatmentItem {
  const TreatmentItem({
    required this.drug,
    this.dose,
    this.route,
    this.duration,
    this.localAvailability = 'unknown',
    this.substitute,
    this.notes,
  });

  final String drug;
  final String? dose;
  final String? route;
  final String? duration;
  final String localAvailability;
  final String? substitute;
  final String? notes;

  bool get isAvailable => localAvailability == 'available';

  factory TreatmentItem.fromJson(Map<String, dynamic> json) => TreatmentItem(
        drug: (json['drug'] ?? '').toString(),
        dose: json['dose']?.toString(),
        route: json['route']?.toString(),
        duration: json['duration']?.toString(),
        localAvailability: (json['local_availability'] ?? 'unknown').toString(),
        substitute: json['substitute']?.toString(),
        notes: json['notes']?.toString(),
      );
}

class Referral {
  const Referral({
    required this.needed,
    this.specialty,
    this.urgency = 'none',
    this.reason,
  });

  final bool needed;
  final String? specialty;
  final String urgency;
  final String? reason;

  factory Referral.fromJson(Map<String, dynamic> json) => Referral(
        needed: json['needed'] == true,
        specialty: json['specialty']?.toString(),
        urgency: (json['urgency'] ?? 'none').toString(),
        reason: json['reason']?.toString(),
      );
}

class ClinicalSuggestion {
  const ClinicalSuggestion({
    this.differentials = const <Differential>[],
    this.redFlags = const <RedFlagBanner>[],
    this.treatmentItems = const <TreatmentItem>[],
    this.nonPharmacological = const <String>[],
    this.recommendedTests = const <String>[],
    this.followUpQuestions = const <String>[],
    this.referral = const Referral(needed: false),
    this.insufficientData = false,
    this.treatmentBlockedReason,
    this.treatmentNotes,
    this.riskScore = 0,
    this.riskBand = 'low',
  });

  final List<Differential> differentials;
  final List<RedFlagBanner> redFlags;
  final List<TreatmentItem> treatmentItems;
  final List<String> nonPharmacological;
  final List<String> recommendedTests;
  final List<String> followUpQuestions;
  final Referral referral;
  final bool insufficientData;
  final String? treatmentBlockedReason;
  final String? treatmentNotes;
  final double riskScore;
  final String riskBand;

  /// True when the deterministic layer fired. The UI must render this first,
  /// above everything else, in red.
  bool get hasImmediateRedFlag => redFlags.any((f) => f.isImmediate);

  factory ClinicalSuggestion.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> treatment =
        (json['treatment'] as Map?)?.cast<String, dynamic>() ??
            <String, dynamic>{};
    final Map<String, dynamic> risk =
        (json['risk'] as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};

    return ClinicalSuggestion(
      differentials: _mapList(json['differentials'], Differential.fromJson),
      redFlags: _mapList(json['red_flags'], RedFlagBanner.fromJson),
      treatmentItems: _mapList(treatment['items'], TreatmentItem.fromJson),
      nonPharmacological: _stringList(treatment['non_pharmacological']),
      recommendedTests: _mapList(
        json['recommended_tests'],
        (Map<String, dynamic> m) => (m['name'] ?? '').toString(),
      ),
      followUpQuestions: _stringList(json['follow_up_questions']),
      referral: Referral.fromJson(
        (json['referral'] as Map?)?.cast<String, dynamic>() ??
            <String, dynamic>{},
      ),
      insufficientData: json['insufficient_data'] == true,
      treatmentBlockedReason: treatment['blocked_reason']?.toString(),
      treatmentNotes: treatment['notes']?.toString(),
      riskScore: (risk['score'] as num?)?.toDouble() ?? 0,
      riskBand: (risk['band'] ?? 'low').toString(),
    );
  }

  static ClinicalSuggestion fromJsonString(String source) =>
      ClinicalSuggestion.fromJson(
        (jsonDecode(source) as Map).cast<String, dynamic>(),
      );
}

List<String> _stringList(dynamic value) =>
    value is List ? value.map((e) => e.toString()).toList() : <String>[];

List<T> _mapList<T>(dynamic value, T Function(Map<String, dynamic>) build) {
  if (value is! List) return <T>[];
  return value
      .whereType<Map>()
      .map((e) => build(e.cast<String, dynamic>()))
      .toList();
}
