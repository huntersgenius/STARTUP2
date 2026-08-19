import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sihhatai/data/local/database.dart';
import 'package:sihhatai/data/remote/api_client.dart';
import 'package:sihhatai/data/repository.dart';
import 'package:sihhatai/features/sync/sync_engine.dart';

/// A server we can take offline at will.
class FakeApi implements ApiClient {
  FakeApi();

  bool online = true;
  final List<Map<String, dynamic>> received = <Map<String, dynamic>>[];
  final Map<String, String> serverIds = <String, String>{};
  int syncCalls = 0;

  @override
  Future<List<Map<String, dynamic>>> sync({
    required String deviceId,
    required List<Map<String, dynamic>> operations,
  }) async {
    syncCalls++;
    if (!online) {
      throw ApiException('no route to host', transient: true);
    }
    final List<Map<String, dynamic>> results = <Map<String, dynamic>>[];
    for (final Map<String, dynamic> op in operations) {
      final String operationId = op['operation_id'].toString();
      // The real server is idempotent on operation_id; the fake must be too,
      // or the test would not exercise replay.
      if (serverIds.containsKey(operationId)) {
        results.add(<String, dynamic>{
          'operation_id': operationId,
          'status': 'duplicate',
          'server_id': serverIds[operationId],
        });
        continue;
      }
      received.add(op);
      final String serverId = 'srv-${serverIds.length + 1}';
      serverIds[operationId] = serverId;
      results.add(<String, dynamic>{
        'operation_id': operationId,
        'status': 'applied',
        'server_id': serverId,
      });
    }
    return results;
  }

  @override
  Future<Map<String, dynamic>> analyze(String consultationId,
      {bool offline = false}) async {
    if (!online) throw ApiException('offline', transient: true);
    return <String, dynamic>{
      'suggestion_id': 'sug-1',
      'payload': <String, dynamic>{'differentials': <dynamic>[]},
      'model': 'test',
      'degraded': false,
    };
  }

  @override
  Future<Map<String, dynamic>> recordDecision(
    String suggestionId, {
    required String action,
    String? finalText,
    String? reason,
  }) async {
    if (!online) throw ApiException('offline', transient: true);
    return <String, dynamic>{'id': 'dec-1', 'action': action};
  }

  @override
  Future<TokenPair> login(String email, String password) async =>
      const TokenPair(accessToken: 'a', refreshToken: 'r');

  @override
  Future<String> refresh(String refreshToken) async => 'a';

  @override
  void setAccessToken(String? token) {}
}

void main() {
  late AppDatabase db;
  late FakeApi api;
  late ClinicalRepository repository;
  late SyncEngine engine;

  setUp(() {
    db = AppDatabase(NativeDatabase.memory());
    api = FakeApi();
    repository = ClinicalRepository(db: db, api: api);
    engine = SyncEngine(db: db, api: api, deviceId: 'tablet-test');
  });

  tearDown(() async => db.close());

  group('offline capture', () {
    test('a consultation created with no network is stored and queued',
        () async {
      api.online = false;
      final LocalPatient patient = await repository.createPatient(
        clinicId: 'clinic-1',
        fullName: 'Aziza Yusupova',
      );
      final LocalConsultation consultation =
          await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'clinic-1',
        chiefComplaint: "3 kundan beri yo'tal va isitma",
        language: 'uz',
        vitals: <String, dynamic>{'temperature_c': 38.4},
      );

      expect(consultation.chiefComplaint, contains('yo'));
      expect(await engine.pendingCount(), 2);
      // Nothing left the device, and nothing was lost.
      expect(api.received, isEmpty);
    });

    test('a failed sync keeps every outbox row', () async {
      api.online = false;
      final LocalPatient patient =
          await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'c',
        chiefComplaint: 'bosh og\'rig\'i',
        language: 'uz',
      );

      final SyncOutcome outcome = await engine.syncOnce();
      expect(outcome.error, isNotNull);
      expect(outcome.applied, 0);
      // The invariant that matters: a failure never deletes work.
      expect(await engine.pendingCount(), 2);
    });

    test('records reach the server when the connection returns', () async {
      api.online = false;
      final LocalPatient patient =
          await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'c',
        chiefComplaint: 'ich ketishi',
        language: 'uz',
      );
      await engine.syncOnce();

      api.online = true;
      // Backoff was scheduled, so the engine is asked with a later clock.
      final SyncEngine later = SyncEngine(
        db: db,
        api: api,
        deviceId: 'tablet-test',
        now: () => DateTime.now().add(const Duration(hours: 2)),
      );
      final SyncOutcome outcome = await later.syncOnce();

      expect(outcome.applied, 2);
      expect(await later.pendingCount(), 0);
      expect(api.received.length, 2);

      final LocalConsultation stored =
          (await db.consultationsForPatient(patient.id)).single;
      expect(stored.serverId, isNotNull);
      expect(stored.syncedAt, isNotNull);
    });

    test('replaying the same operation does not duplicate on the server',
        () async {
      final LocalPatient patient =
          await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'c',
        chiefComplaint: 'isitma',
        language: 'uz',
      );

      await engine.syncOnce();
      final int afterFirst = api.received.length;
      await engine.syncOnce();

      expect(api.received.length, afterFirst);
      expect(await engine.pendingCount(), 0);
    });

    test('a consultation queued against a local patient id is rewritten',
        () async {
      api.online = false;
      final LocalPatient patient =
          await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'c',
        chiefComplaint: 'yo\'tal',
        language: 'uz',
      );

      api.online = true;
      await engine.syncOnce();

      // The consultation operation must reference the server's patient id,
      // not the local one, or the server rejects it as an orphan.
      final Map<String, dynamic> consultationOp =
          api.received.firstWhere((op) => op['entity_type'] == 'consultation');
      final Map<String, dynamic> data =
          (consultationOp['data'] as Map).cast<String, dynamic>();
      expect(data['patient_id'], startsWith('srv-'));
    });

    test('a rejected operation is kept, not dropped', () async {
      final LocalPatient patient =
          await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'c',
        chiefComplaint: 'yo\'tal',
        language: 'uz',
      );

      // A server that rejects everything.
      final SyncEngine rejecting = SyncEngine(
        db: db,
        api: _RejectingApi(),
        deviceId: 'tablet-test',
      );
      final SyncOutcome outcome = await rejecting.syncOnce();

      expect(outcome.rejected, greaterThan(0));
      // Losing a patient record because the server disliked it is not an
      // option; the row stays for support to look at.
      expect(await rejecting.pendingCount(), 2);
    });

    test('backoff grows with each failed attempt', () async {
      api.online = false;
      await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');

      await engine.syncOnce();
      final OutboxEntry first = (await db.select(db.outbox).get()).single;
      expect(first.attempts, 1);
      expect(first.nextAttemptAt, isNotNull);

      final SyncEngine later = SyncEngine(
        db: db,
        api: api,
        deviceId: 'tablet-test',
        now: () => DateTime.now().add(const Duration(hours: 1)),
      );
      await later.syncOnce();
      final OutboxEntry second = (await db.select(db.outbox).get()).single;
      expect(second.attempts, 2);
      expect(second.lastError, isNotNull);
    });

    test('a row still backing off is not retried early', () async {
      api.online = false;
      await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      await engine.syncOnce();
      final int callsAfterFirst = api.syncCalls;

      // Immediately again — the row is in backoff, so nothing should be sent.
      await engine.syncOnce();
      expect(api.syncCalls, callsAfterFirst);
    });

    test('the decision is stored locally even when the server is unreachable',
        () async {
      final LocalPatient patient =
          await repository.createPatient(clinicId: 'c', fullName: 'Test Bemor');
      final LocalConsultation consultation =
          await repository.createConsultation(
        patientId: patient.id,
        clinicId: 'c',
        chiefComplaint: 'yo\'tal',
        language: 'uz',
      );
      await engine.syncOnce();

      final LocalConsultation synced =
          (await db.consultationById(consultation.id))!;
      final LocalSuggestion suggestion = await repository.analyze(synced);

      api.online = false;
      await repository.recordDecision(
        suggestion: suggestion,
        action: 'accept',
      );

      final LocalSuggestion stored = await (db.select(db.suggestions)
            ..where((s) => s.id.equals(suggestion.id)))
          .getSingle();
      expect(stored.decisionAction, 'accept');
      expect(stored.decidedAt, isNotNull);
      // And it is queued so the audit trail eventually gets it.
      final List<OutboxEntry> pending = await db.select(db.outbox).get();
      expect(pending.any((e) => e.entityType == 'decision'), isTrue);
    });
  });
}

class _RejectingApi extends FakeApi {
  @override
  Future<List<Map<String, dynamic>>> sync({
    required String deviceId,
    required List<Map<String, dynamic>> operations,
  }) async {
    return operations
        .map((op) => <String, dynamic>{
              'operation_id': op['operation_id'],
              'status': 'rejected',
              'detail': 'patient not found',
            })
        .toList();
  }
}
