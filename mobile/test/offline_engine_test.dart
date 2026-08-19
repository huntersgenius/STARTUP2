import 'package:flutter_test/flutter_test.dart';
import 'package:sihhatai/features/consultation/offline_engine.dart';
import 'package:sihhatai/features/consultation/symptom_matcher.dart';

void main() {
  group('symptom matching', () {
    test('recognises Uzbek free text', () {
      expect(
        extractConcepts("3 kundan beri yo'tal va isitma bor"),
        containsAll(<String>['cough', 'fever']),
      );
    });

    test('recognises Russian free text', () {
      expect(
        extractConcepts('боль в груди и одышка'),
        containsAll(<String>['chest_pain', 'dyspnea']),
      );
    });

    test('apostrophe variants resolve to the same concept', () {
      for (final String text in <String>[
        "yo'tal",
        'yo’tal',
        'yotal',
        'YO\'TAL'
      ]) {
        expect(extractConcepts(text), contains('cough'), reason: text);
      }
    });

    test('longest match wins', () {
      final Set<String> found = extractConcepts('qonli ich ketishi bor');
      expect(found, contains('bloody_diarrhea'));
      expect(found, isNot(contains('diarrhea')));
    });

    test('vitals imply concepts on their own', () {
      expect(
        conceptsFromVitals(
            <String, dynamic>{'systolic_bp': 165, 'diastolic_bp': 95}),
        contains('hypertension'),
      );
      expect(
        conceptsFromVitals(<String, dynamic>{'temperature_c': 38.4}),
        contains('fever'),
      );
      expect(conceptsFromVitals(<String, dynamic>{'spo2': 88}),
          contains('dyspnea'));
      expect(conceptsFromVitals(<String, dynamic>{'spo2': 98}), isEmpty);
    });

    test('every chip has a label in both languages', () {
      for (final String concept in kSymptomChips) {
        expect(conceptLabel(concept, 'uz'), isNotEmpty);
        expect(conceptLabel(concept, 'ru'), isNotEmpty);
        expect(conceptLabel(concept, 'uz'),
            isNot(equals(conceptLabel(concept, 'ru'))));
      }
    });
  });

  group('offline assessment', () {
    const OfflineEngine engine = OfflineEngine();

    test('fires red flags with no server', () {
      final result = engine.assess(
        freeText: "ko'krak og'rig'i va nafas qisishi",
        selectedConcepts: const <String>{},
        vitals: const <String, dynamic>{},
      );
      expect(result.redFlags.map((f) => f.code), contains('acs_suspected'));
      expect(result.referral.needed, isTrue);
      expect(result.referral.urgency, 'immediate');
    });

    test('never invents a differential offline', () {
      final result = engine.assess(
        freeText: "3 kundan beri yo'tal va isitma",
        selectedConcepts: const <String>{},
        vitals: const <String, dynamic>{'temperature_c': 38.5},
      );
      // Without retrieval, a citation or a formulary check, a ranked list
      // would be a guess dressed up as advice.
      expect(result.differentials, isEmpty);
      expect(result.insufficientData, isTrue);
      expect(result.followUpQuestions, isNotEmpty);
    });

    test('asks for a weight when the patient is a child', () {
      final result = engine.assess(
        freeText: 'ich ketishi',
        selectedConcepts: const <String>{},
        vitals: const <String, dynamic>{},
        ageYears: 4,
      );
      expect(result.followUpQuestions.first, contains('vazn'));
    });

    test('does not ask for a weight when one is recorded', () {
      final result = engine.assess(
        freeText: 'ich ketishi',
        selectedConcepts: const <String>{},
        vitals: const <String, dynamic>{'weight_kg': 15},
        ageYears: 4,
      );
      expect(result.followUpQuestions.first, isNot(contains('vazn')));
    });

    test('questions follow the selected language', () {
      final result = engine.assess(
        freeText: 'кашель',
        selectedConcepts: const <String>{},
        vitals: const <String, dynamic>{},
        language: 'ru',
      );
      expect(result.followUpQuestions.first, contains('Когда'));
    });

    test('chips and free text combine', () {
      final result = engine.assess(
        freeText: "ko'krak og'rig'i",
        selectedConcepts: const <String>{'dyspnea'},
        vitals: const <String, dynamic>{},
      );
      expect(result.redFlags.map((f) => f.code), contains('acs_suspected'));
    });
  });
}
