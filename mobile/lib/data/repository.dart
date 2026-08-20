import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import 'local/database.dart';
import 'models/suggestion.dart';
import 'remote/api_client.dart';

/// The only place the app writes clinical data.
///
/// Every mutation lands in the local database *first*, with its outbox row in
/// the same transaction. The network is treated as an optimisation, never as a
/// prerequisite: a consultation is saved and safe before any request is made.
class ClinicalRepository {
  ClinicalRepository({
    required AppDatabase db,
    required ApiClient api,
    Uuid uuid = const Uuid(),
    DateTime Function() now = DateTime.now,
  })  : _db = db,
        _api = api,
        _uuid = uuid,
        _now = now;

  final AppDatabase _db;
  final ApiClient _api;
  final Uuid _uuid;
  final DateTime Function() _now;

  AppDatabase get database => _db;

  Future<LocalPatient> createPatient({
    required String clinicId,
    required String fullName,
    String? phone,
    String? address,
    DateTime? dob,
    String sex = 'unknown',
    List<String> chronicFlags = const <String>[],
  }) async {
    final String localId = _uuid.v4();
    final DateTime timestamp = _now().toUtc();
    final String mrn = 'P-${localId.substring(0, 8).toUpperCase()}';

    final PatientsCompanion patient = PatientsCompanion.insert(
      id: localId,
      clinicId: clinicId,
      mrn: mrn,
      fullName: fullName,
      phone: Value(phone),
      address: Value(address),
      dob: Value(dob),
      sex: Value(sex),
      chronicFlagsJson: Value(jsonEncode(chronicFlags)),
      updatedAt: timestamp,
    );

    await _db.savePatientWithOutbox(
      patient: patient,
      entry: OutboxCompanion.insert(
        operationId: _uuid.v4(),
        entityType: 'patient',
        op: 'create',
        localId: localId,
        payloadJson: jsonEncode(<String, dynamic>{
          'pii': <String, dynamic>{
            'full_name': fullName,
            if (phone != null) 'phone': phone,
            if (address != null) 'address': address,
          },
          'mrn': mrn,
          if (dob != null) 'dob': dob.toIso8601String().split('T').first,
          'sex': sex,
          'chronic_flags': chronicFlags,
        }),
        updatedAt: timestamp,
        createdAt: timestamp,
      ),
    );

    return (await _db.patientById(localId))!;
  }

  /// Create a consultation. Works identically online and offline — the only
  /// difference is how quickly the outbox drains.
  Future<LocalConsultation> createConsultation({
    required String patientId,
    required String clinicId,
    required String chiefComplaint,
    required String language,
    Map<String, dynamic> structuredSymptoms = const <String, dynamic>{},
    Map<String, dynamic> vitals = const <String, dynamic>{},
    bool offline = true,
  }) async {
    final String localId = _uuid.v4();
    final DateTime timestamp = _now().toUtc();
    final LocalPatient? patient = await _db.patientById(patientId);
    // If the patient has already synced, reference the server id; otherwise
    // the local id, which the sync engine rewrites once the patient lands.
    final String referencedPatientId = patient?.serverId ?? patientId;

    await _db.saveConsultationWithOutbox(
      consultation: ConsultationsCompanion.insert(
        id: localId,
        patientId: patientId,
        clinicId: clinicId,
        chiefComplaint: chiefComplaint,
        language: Value(language),
        structuredSymptomsJson: Value(jsonEncode(structuredSymptoms)),
        vitalsJson: Value(jsonEncode(vitals)),
        createdOffline: Value(offline),
        createdAt: timestamp,
        updatedAt: timestamp,
      ),
      entry: OutboxCompanion.insert(
        operationId: _uuid.v4(),
        entityType: 'consultation',
        op: 'create',
        localId: localId,
        payloadJson: jsonEncode(<String, dynamic>{
          'patient_id': referencedPatientId,
          'chief_complaint': chiefComplaint,
          'language': language,
          'structured_symptoms': structuredSymptoms,
          'vitals': vitals,
          'client_uuid': localId,
          'created_offline': offline,
        }),
        updatedAt: timestamp,
        createdAt: timestamp,
      ),
    );

    return (await _db.consultationById(localId))!;
  }

  /// Ask the server for an assessment. Callers fall back to `OfflineEngine`
  /// when this throws a transient error.
  Future<LocalSuggestion> analyze(LocalConsultation consultation) async {
    final String? serverId = consultation.serverId;
    if (serverId == null) {
      throw ApiException(
        'consultation has not reached the server yet',
        transient: true,
      );
    }
    final Map<String, dynamic> response = await _api.analyze(serverId);
    final Map<String, dynamic> payload =
        (response['payload'] as Map).cast<String, dynamic>();

    final String localId = _uuid.v4();
    await _db.into(_db.suggestions).insertOnConflictUpdate(
          SuggestionsCompanion.insert(
            id: localId,
            serverId: Value(response['suggestion_id']?.toString()),
            consultationId: consultation.id,
            payloadJson: jsonEncode(payload),
            model: Value(response['model']?.toString() ?? 'unknown'),
            degraded: Value(response['degraded'] == true),
            createdAt: _now().toUtc(),
          ),
        );
    return (await (_db.select(_db.suggestions)
          ..where((s) => s.id.equals(localId)))
        .getSingle());
  }

  /// Record the clinician's decision.
  ///
  /// Written locally first and queued, so a decision made in a basement with
  /// no signal is never lost — the audit trail depends on it reaching the
  /// server eventually, not immediately.
  Future<void> recordDecision({
    required LocalSuggestion suggestion,
    required String action,
    String? finalText,
    String? reason,
  }) async {
    final DateTime timestamp = _now().toUtc();
    await (_db.update(_db.suggestions)
          ..where((s) => s.id.equals(suggestion.id)))
        .write(
      SuggestionsCompanion(
        decisionAction: Value(action),
        decisionText: Value(finalText),
        decisionReason: Value(reason),
        decidedAt: Value(timestamp),
      ),
    );

    final String? serverId = suggestion.serverId;

    if (serverId == null) {
      // The suggestion never reached the server — it was produced on the
      // device. Queue the assessment and the decision together, keyed by the
      // consultation's client id, so the server can attach both once the
      // consultation itself has synced.
      await _queueOfflineAssessment(
          suggestion, action, finalText, reason, timestamp);
      return;
    }

    try {
      await _api.recordDecision(
        serverId,
        action: action,
        finalText: finalText,
        reason: reason,
      );
    } on ApiException {
      // The decision is already stored locally; the outbox carries it later.
      await _db.into(_db.outbox).insertOnConflictUpdate(
            OutboxCompanion.insert(
              operationId: _uuid.v4(),
              entityType: 'decision',
              op: 'create',
              localId: suggestion.id,
              serverId: Value(serverId),
              payloadJson: jsonEncode(<String, dynamic>{
                'action': action,
                if (finalText != null) 'final_text': finalText,
                if (reason != null) 'reason': reason,
              }),
              updatedAt: timestamp,
              createdAt: timestamp,
            ),
          );
    }
  }

  Future<void> _queueOfflineAssessment(
    LocalSuggestion suggestion,
    String action,
    String? finalText,
    String? reason,
    DateTime timestamp,
  ) async {
    final LocalConsultation? consultation =
        await _db.consultationById(suggestion.consultationId);
    if (consultation == null) return;

    await _db.into(_db.outbox).insertOnConflictUpdate(
          OutboxCompanion.insert(
            operationId: _uuid.v4(),
            entityType: 'offline_assessment',
            op: 'create',
            localId: suggestion.id,
            payloadJson: jsonEncode(<String, dynamic>{
              if (consultation.serverId != null)
                'consultation_server_id': consultation.serverId,
              'consultation_client_uuid': consultation.id,
              'payload': jsonDecode(suggestion.payloadJson),
              'prompt_version': 'device-rules',
              'decision': <String, dynamic>{
                'action': action,
                if (finalText != null) 'final_text': finalText,
                if (reason != null) 'reason': reason,
                'decided_at': timestamp.toIso8601String(),
              },
            }),
            updatedAt: timestamp,
            createdAt: timestamp,
          ),
        );
  }

  /// Persist a suggestion the device produced with no server.
  ///
  /// Without this row there is nothing for the clinician's decision to attach
  /// to, and the decision was silently dropped — the consultation reached the
  /// server with no evidence a human had reviewed the output.
  Future<LocalSuggestion> saveOfflineSuggestion({
    required String consultationId,
    required Map<String, dynamic> payload,
  }) async {
    final String localId = _uuid.v4();
    await _db.into(_db.suggestions).insertOnConflictUpdate(
          SuggestionsCompanion.insert(
            id: localId,
            consultationId: consultationId,
            payloadJson: jsonEncode(payload),
            // Named so nobody reading the record later mistakes a device rule
            // table for a model.
            model: const Value('offline-rules'),
            degraded: const Value(true),
            createdAt: _now().toUtc(),
          ),
        );
    return (_db.select(_db.suggestions)..where((s) => s.id.equals(localId)))
        .getSingle();
  }

  Future<ClinicalSuggestion?> latestSuggestion(String consultationId) async {
    final LocalSuggestion? row = await (_db.select(_db.suggestions)
          ..where((s) => s.consultationId.equals(consultationId))
          ..orderBy([(s) => OrderingTerm.desc(s.createdAt)])
          ..limit(1))
        .getSingleOrNull();
    if (row == null) return null;
    return ClinicalSuggestion.fromJsonString(row.payloadJson);
  }
}
