import 'package:flutter_test/flutter_test.dart';
import 'package:sihhatai/features/consultation/local_red_flags.dart';

Set<String> codes(LocalCase c) =>
    evaluateLocalRedFlags(c).map((f) => f.code).toSet();

void main() {
  group('on-device red flags', () {
    test('nothing fires on an empty case', () {
      expect(evaluateLocalRedFlags(const LocalCase(concepts: <String>{})),
          isEmpty);
    });

    test('chest pain with dyspnea fires ACS', () {
      expect(
        codes(const LocalCase(concepts: <String>{'chest_pain', 'dyspnea'})),
        contains('acs_suspected'),
      );
    });

    test('chest pain alone does not fire ACS', () {
      expect(
        codes(const LocalCase(concepts: <String>{'chest_pain'})),
        isNot(contains('acs_suspected')),
      );
    });

    test('stroke signs fire FAST', () {
      expect(
        codes(const LocalCase(concepts: <String>{'slurred_speech'})),
        contains('stroke_fast'),
      );
    });

    test('stiff neck with fever fires meningism', () {
      expect(
        codes(const LocalCase(concepts: <String>{'neck_stiffness', 'fever'})),
        contains('meningism'),
      );
    });

    test('stiff neck alone does not fire meningism', () {
      expect(
        codes(const LocalCase(concepts: <String>{'neck_stiffness'})),
        isNot(contains('meningism')),
      );
    });

    test('low saturation fires hypoxia', () {
      expect(codes(const LocalCase(concepts: <String>{}, spo2: 88)),
          contains('hypoxia'));
      expect(codes(const LocalCase(concepts: <String>{}, spo2: 96)), isEmpty);
    });

    test('IMCI danger sign fires only in a child', () {
      expect(
        codes(const LocalCase(concepts: <String>{'lethargy'}, ageYears: 2)),
        contains('imci_danger_sign'),
      );
      expect(
        codes(const LocalCase(concepts: <String>{'lethargy'}, ageYears: 40)),
        isNot(contains('imci_danger_sign')),
      );
    });

    test('childhood diarrhoea with dehydration fires', () {
      expect(
        codes(const LocalCase(
          concepts: <String>{'diarrhea', 'dehydration'},
          ageYears: 3,
        )),
        contains('pediatric_dehydration'),
      );
    });

    test('raised blood pressure in pregnancy fires pre-eclampsia', () {
      expect(
        codes(const LocalCase(
          concepts: <String>{},
          pregnant: true,
          systolicBp: 155,
        )),
        contains('preeclampsia_suspected'),
      );
      expect(
        codes(const LocalCase(concepts: <String>{}, systolicBp: 155)),
        isNot(contains('preeclampsia_suspected')),
      );
    });

    test('TB triad needs a prolonged cough', () {
      expect(
        codes(const LocalCase(
          concepts: <String>{'cough', 'night_sweats'},
          durationDays: 30,
        )),
        contains('tb_suspected'),
      );
      expect(
        codes(const LocalCase(
          concepts: <String>{'cough', 'night_sweats'},
          durationDays: 3,
        )),
        isNot(contains('tb_suspected')),
      );
    });

    test('glucose emergencies fire in both directions', () {
      expect(codes(const LocalCase(concepts: <String>{}, glucoseMmol: 2.0)),
          contains('hypoglycemia'));
      expect(codes(const LocalCase(concepts: <String>{}, glucoseMmol: 25.0)),
          contains('hyperglycemic_emergency'));
      expect(codes(const LocalCase(concepts: <String>{}, glucoseMmol: 5.5)),
          isEmpty);
    });

    test('immediate flags sort before less urgent ones', () {
      final List<LocalRedFlag> flags = evaluateLocalRedFlags(const LocalCase(
        concepts: <String>{'cough', 'night_sweats', 'chest_pain', 'dyspnea'},
        durationDays: 30,
      ));
      expect(flags.first.urgency, 'immediate');
    });

    test('every flag has Uzbek and Russian text that differ', () {
      final List<LocalRedFlag> flags = evaluateLocalRedFlags(
        const LocalCase(concepts: <String>{'chest_pain', 'dyspnea'}),
      );
      expect(flags, isNotEmpty);
      for (final LocalRedFlag flag in flags) {
        expect(flag.messageUz.length, greaterThan(10));
        expect(flag.messageRu.length, greaterThan(10));
        expect(flag.messageUz, isNot(equals(flag.messageRu)));
        expect(flag.referTo, isNotEmpty);
      }
    });

    test('device codes are a subset of the server rule table', () {
      // Kept in step with backend/app/ai/red_flags.py. If the server renames a
      // code, this list must change with it or the two will disagree about
      // what fired.
      const Set<String> serverCodes = <String>{
        'acs_suspected',
        'hypoxia',
        'respiratory_distress',
        'airway_compromise',
        'sepsis_suspected',
        'stroke_fast',
        'meningism',
        'seizure',
        'imci_danger_sign',
        'pediatric_dehydration',
        'pregnancy_bleeding',
        'preeclampsia_suspected',
        'gi_bleeding',
        'hemoptysis',
        'tb_suspected',
        'hyperglycemic_emergency',
        'hypoglycemia',
        'hypertensive_emergency',
        'severe_anemia',
      };
      const List<LocalCase> probes = <LocalCase>[
        LocalCase(concepts: <String>{'chest_pain', 'dyspnea'}),
        LocalCase(concepts: <String>{'slurred_speech'}),
        LocalCase(concepts: <String>{'neck_stiffness', 'fever'}),
        LocalCase(concepts: <String>{}, spo2: 85),
        LocalCase(concepts: <String>{'diarrhea', 'dehydration'}, ageYears: 2),
        LocalCase(concepts: <String>{'pregnancy_bleeding'}),
        LocalCase(concepts: <String>{}, pregnant: true, systolicBp: 160),
        LocalCase(concepts: <String>{'melena'}),
        LocalCase(concepts: <String>{'cough', 'weight_loss'}, durationDays: 40),
        LocalCase(concepts: <String>{}, glucoseMmol: 1.9),
        LocalCase(concepts: <String>{}, glucoseMmol: 30),
      ];
      for (final LocalCase probe in probes) {
        for (final String code in codes(probe)) {
          expect(serverCodes, contains(code),
              reason: '$code is not a server rule code');
        }
      }
    });
  });
}
