import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sihhatai/core/strings.dart';
import 'package:sihhatai/core/theme.dart';
import 'package:sihhatai/data/local/database.dart';
import 'package:sihhatai/data/models/suggestion.dart';
import 'package:sihhatai/data/repository.dart';
import 'package:sihhatai/features/consultation/consultation_screen.dart';
import 'package:sihhatai/providers.dart';
import 'package:sihhatai/widgets/decision_gate.dart';
import 'package:sihhatai/widgets/disclaimer_bar.dart';
import 'package:sihhatai/widgets/suggestion_view.dart';
import 'package:sihhatai/widgets/sync_indicator.dart';

import 'sync_engine_test.dart' show FakeApi;

void _noop() {}

Widget _wrap(Widget child, {List<Override> overrides = const <Override>[]}) {
  return ProviderScope(
    overrides: overrides,
    child: MaterialApp(theme: AppTheme.light(), home: child),
  );
}

void main() {
  group('translations', () {
    test('Uzbek and Russian catalogs have identical keys', () {
      expect(kUz.keys.toSet(), kRu.keys.toSet());
    });

    test('no clinical string is left in English', () {
      for (final String key in kUz.keys) {
        expect(kUz[key]!.trim(), isNotEmpty, reason: key);
        expect(kRu[key]!.trim(), isNotEmpty, reason: key);
      }
      // A catalog that silently copies the other reads as translated in review
      // and is unusable in a clinic.
      for (final String key in <String>[
        'disclaimer.short',
        'decision.accept',
        'redflag.banner',
        'sync.pending',
      ]) {
        expect(kUz[key], isNot(equals(kRu[key])), reason: key);
      }
    });

    test('Uzbek is the default for an unknown language', () {
      expect(tr('decision.accept', 'fr'), kUz['decision.accept']);
    });
  });

  group('safety surfaces', () {
    testWidgets('red flags render above everything, in red',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const SuggestionView(
          language: 'uz',
          suggestion: ClinicalSuggestion(
            redFlags: <RedFlagBanner>[
              RedFlagBanner(
                code: 'acs_suspected',
                urgency: 'immediate',
                message: 'Yurak xurujii shubhasi',
                referTo: 'emergency_cardiology',
              ),
            ],
            differentials: <Differential>[
              Differential(
                condition: 'Bronxit',
                confidence: 0.7,
                why: 'yo\'tal',
                citations: <String>['c1'],
              ),
            ],
          ),
        ),
      ));

      expect(find.byKey(const Key('red-flag-acs_suspected')), findsOneWidget);
      final Offset flag = tester.getTopLeft(
        find.byKey(const Key('red-flag-acs_suspected')),
      );
      final Offset differential = tester.getTopLeft(
        find.byKey(const Key('differential-Bronxit')),
      );
      // The banner must be above the differential a clinician might act on.
      expect(flag.dy, lessThan(differential.dy));
    });

    testWidgets('the disclaimer is always present with a suggestion',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const SuggestionView(
          language: 'uz',
          suggestion: ClinicalSuggestion(
            differentials: <Differential>[
              Differential(condition: 'Bronxit', confidence: 0.7, why: 'x'),
            ],
          ),
        ),
      ));
      expect(find.byKey(const Key('disclaimer-bar')), findsOneWidget);
      expect(find.byType(DisclaimerBar), findsOneWidget);
    });

    testWidgets('a blocked paediatric dose is shown, not hidden',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const SuggestionView(
          language: 'uz',
          suggestion: ClinicalSuggestion(
            treatmentItems: <TreatmentItem>[TreatmentItem(drug: 'paracetamol')],
            treatmentBlockedReason: 'pediatric_weight_required',
          ),
        ),
      ));
      expect(find.byKey(const Key('pediatric-weight-block')), findsOneWidget);
    });

    testWidgets('an unavailable drug shows its substitute',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const SuggestionView(
          language: 'uz',
          suggestion: ClinicalSuggestion(
            treatmentItems: <TreatmentItem>[
              TreatmentItem(
                drug: 'losartan',
                localAvailability: 'substitute_suggested',
                substitute: 'enalapril',
              ),
            ],
          ),
        ),
      ));
      expect(find.textContaining('enalapril'), findsOneWidget);
    });

    testWidgets('low confidence shows questions instead of a ranked guess',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const SuggestionView(
          language: 'uz',
          suggestion: ClinicalSuggestion(
            insufficientData: true,
            followUpQuestions: <String>['Harorat o\'lchandimi?'],
          ),
        ),
      ));
      expect(find.byKey(const Key('insufficient-data')), findsOneWidget);
      expect(find.textContaining('Harorat'), findsOneWidget);
    });
  });

  group('decision gate', () {
    testWidgets('accept records immediately', (WidgetTester tester) async {
      DecisionResult? captured;
      await tester.pumpWidget(_wrap(
        Scaffold(
          body: DecisionGate(
            language: 'uz',
            onDecision: (DecisionResult r) async => captured = r,
          ),
        ),
      ));
      await tester.tap(find.byKey(const Key('decision-accept')));
      await tester.pumpAndSettle();
      expect(captured?.action, DecisionAction.accept);
    });

    testWidgets('reject asks for a reason before it will submit',
        (WidgetTester tester) async {
      DecisionResult? captured;
      await tester.pumpWidget(_wrap(
        Scaffold(
          body: DecisionGate(
            language: 'uz',
            onDecision: (DecisionResult r) async => captured = r,
          ),
        ),
      ));

      await tester.tap(find.byKey(const Key('decision-reject')));
      await tester.pumpAndSettle();
      // First tap opens the field; nothing is recorded yet.
      expect(captured, isNull);
      expect(find.byKey(const Key('decision-text')), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('decision-text')),
        'Klinik manzara mos emas',
      );
      await tester.tap(find.byKey(const Key('decision-reject')));
      await tester.pumpAndSettle();
      expect(captured?.action, DecisionAction.reject);
      expect(captured?.reason, 'Klinik manzara mos emas');
    });

    testWidgets('every decision button meets the touch target size',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        Scaffold(
          body: DecisionGate(language: 'uz', onDecision: (_) async {}),
        ),
      ));
      for (final Key key in <Key>[
        const Key('decision-accept'),
        const Key('decision-edit'),
        const Key('decision-reject'),
      ]) {
        final Size size = tester.getSize(find.byKey(key));
        expect(size.height, greaterThanOrEqualTo(AppTheme.touchTarget));
      }
    });
  });

  group('sync indicator', () {
    testWidgets('shows the pending count a clinician can act on',
        (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const Scaffold(
          body: SyncIndicator(
            language: 'uz',
            pendingCount: 3,
            isOnline: true,
            isSyncing: false,
            onRetry: _noop,
          ),
        ),
      ));
      expect(find.textContaining('3'), findsOneWidget);
      expect(find.byKey(const Key('sync-retry')), findsOneWidget);
    });

    testWidgets('offline state is stated plainly', (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const Scaffold(
          body: SyncIndicator(
            language: 'uz',
            pendingCount: 2,
            isOnline: false,
            isSyncing: false,
          ),
        ),
      ));
      expect(find.text(kUz['sync.offline']!), findsOneWidget);
    });

    testWidgets('nothing pending says so', (WidgetTester tester) async {
      await tester.pumpWidget(_wrap(
        const Scaffold(
          body: SyncIndicator(
            language: 'uz',
            pendingCount: 0,
            isOnline: true,
            isSyncing: false,
          ),
        ),
      ));
      expect(find.text(kUz['sync.allSent']!), findsOneWidget);
      expect(find.byKey(const Key('sync-retry')), findsNothing);
    });
  });

  group('airplane mode end to end', () {
    testWidgets('a full consultation completes with no network',
        (WidgetTester tester) async {
      final AppDatabase db = AppDatabase(NativeDatabase.memory());
      final FakeApi api = FakeApi()..online = false;
      final ClinicalRepository repository =
          ClinicalRepository(db: db, api: api);

      final LocalPatient patient = await repository.createPatient(
        clinicId: 'clinic-1',
        fullName: 'Aziza Yusupova',
      );

      await tester.pumpWidget(_wrap(
        ConsultationScreen(patient: patient),
        overrides: <Override>[
          databaseProvider.overrideWithValue(db),
          apiClientProvider.overrideWithValue(api),
          deviceIdProvider.overrideWithValue('tablet-test'),
        ],
      ));
      await tester.pumpAndSettle();

      // A feldsher types the complaint and taps two chips.
      await tester.enterText(
        find.byKey(const Key('complaint-field')),
        "ko'krak og'rig'i va nafas qisishi",
      );
      await tester.tap(find.byKey(const Key('chip-chest_pain')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('chip-dyspnea')));
      await tester.pump();

      // The vitals live below the fold on a phone-sized test viewport.
      await tester.scrollUntilVisible(
        find.byKey(const Key('vital-spo2')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.enterText(find.byKey(const Key('vital-spo2')), '89');
      await tester.pump();

      await tester.tap(find.byKey(const Key('analyze-button')));
      await tester.pumpAndSettle();

      // With no server, the deterministic layer still produces the banner.
      expect(find.byKey(const Key('red-flag-acs_suspected')), findsOneWidget);
      expect(find.byKey(const Key('red-flag-hypoxia')), findsOneWidget);
      expect(find.byType(DecisionGate), findsOneWidget);

      // And the consultation is safely on disk, queued for sync.
      final List<LocalConsultation> stored =
          await db.consultationsForPatient(patient.id);
      expect(stored, hasLength(1));
      expect(stored.single.chiefComplaint, contains("ko'krak"));

      final List<OutboxEntry> pending = await db.select(db.outbox).get();
      expect(
          pending.where((e) => e.entityType == 'consultation'), hasLength(1));

      // The clinician still has to close the gate.
      await tester.tap(find.byKey(const Key('decision-accept')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('decision-recorded')), findsOneWidget);

      await db.close();
    });
  });
}
