import '../../data/models/suggestion.dart';
import 'local_red_flags.dart';
import 'symptom_matcher.dart';

/// What the app produces when there is no server.
///
/// It is deliberately *not* a local diagnosis. Without retrieval, a citation
/// or a formulary check, a ranked differential list would be a guess dressed
/// up as advice. What the device can do honestly is:
///
/// - run the deterministic red-flag rules, which need no model at all,
/// - collect the case properly so nothing is lost,
/// - tell the clinician plainly that the full assessment is waiting for a
///   connection.
///
/// If an edge server (Ollama on a clinic mini-PC) is reachable, the app calls
/// it instead and gets a real suggestion; that path lives in the repository,
/// not here.
class OfflineEngine {
  const OfflineEngine();

  ClinicalSuggestion assess({
    required String freeText,
    required Set<String> selectedConcepts,
    required Map<String, dynamic> vitals,
    double? ageYears,
    bool pregnant = false,
    String language = 'uz',
  }) {
    final Set<String> concepts = <String>{
      ...extractConcepts(freeText),
      ...selectedConcepts,
      ...conceptsFromVitals(vitals),
    };

    final LocalCase localCase = LocalCase(
      concepts: concepts,
      ageYears: ageYears,
      pregnant: pregnant,
      temperatureC: (vitals['temperature_c'] as num?)?.toDouble(),
      systolicBp: (vitals['systolic_bp'] as num?)?.toInt(),
      diastolicBp: (vitals['diastolic_bp'] as num?)?.toInt(),
      respiratoryRate: (vitals['respiratory_rate'] as num?)?.toInt(),
      spo2: (vitals['spo2'] as num?)?.toInt(),
      glucoseMmol: (vitals['glucose_mmol'] as num?)?.toDouble(),
      durationDays: (vitals['duration_days'] as num?)?.toDouble(),
    );

    final List<LocalRedFlag> flags = evaluateLocalRedFlags(localCase);

    return ClinicalSuggestion(
      differentials: const <Differential>[],
      redFlags: flags
          .map((f) => RedFlagBanner(
                code: f.code,
                urgency: f.urgency,
                message: f.message(language),
                referTo: f.referTo,
              ))
          .toList(),
      referral: flags.isEmpty
          ? const Referral(needed: false)
          : Referral(
              needed: true,
              specialty: flags.first.referTo,
              urgency: flags.first.urgency,
              reason: flags.first.message(language),
            ),
      insufficientData: true,
      followUpQuestions:
          _questions(language, needsWeight: _needsWeight(ageYears, vitals)),
      riskScore: flags.isEmpty ? 0.1 : 0.8,
      riskBand: flags.isEmpty ? 'low' : 'high',
    );
  }

  static bool _needsWeight(double? ageYears, Map<String, dynamic> vitals) =>
      ageYears != null && ageYears < 12 && vitals['weight_kg'] == null;

  static List<String> _questions(String language, {required bool needsWeight}) {
    final List<String> base = language == 'ru'
        ? <String>[
            'Когда началась жалоба и как менялась?',
            'Измерялась ли температура? Сколько?',
            'Какие ещё есть симптомы?',
            'Какие лекарства принимает пациент?',
          ]
        : <String>[
            'Shikoyat qachon boshlangan va qanday o\'zgargan?',
            'Harorat o\'lchandimi? Necha daraja?',
            'Boshqa qanday belgilar bor?',
            'Qanday dorilar qabul qilinmoqda?',
          ];
    if (!needsWeight) return base;
    final String weight = language == 'ru'
        ? 'Какой вес ребёнка в кг?'
        : 'Bolaning vazni necha kg?';
    return <String>[weight, ...base];
  }
}
