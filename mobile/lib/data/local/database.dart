import 'dart:convert';

import 'package:drift/drift.dart';

part 'database.g.dart';

/// The local store is the record of truth while the tablet is offline.
///
/// Two rules govern this schema:
///
/// 1. **Nothing is ever deleted on sync.** A row that has reached the server
///    is marked, not removed, so a failed sync can never lose a consultation.
/// 2. **Every mutation writes an outbox row in the same transaction** as the
///    data it describes. If the app is killed between the two, the outbox and
///    the data cannot disagree.
@DataClassName('LocalPatient')
class Patients extends Table {
  TextColumn get id => text()();
  TextColumn get serverId => text().nullable()();
  TextColumn get clinicId => text()();
  TextColumn get mrn => text()();

  /// Identifiers stay on the device. They are sent to our own server over TLS
  /// and never to a model provider — the server de-identifies before any
  /// outbound call.
  TextColumn get fullName => text()();
  TextColumn get phone => text().nullable()();
  TextColumn get address => text().nullable()();

  DateTimeColumn get dob => dateTime().nullable()();
  TextColumn get sex => text().withDefault(const Constant('unknown'))();
  TextColumn get chronicFlagsJson => text().withDefault(const Constant('[]'))();
  DateTimeColumn get updatedAt => dateTime()();
  BoolColumn get synced => boolean().withDefault(const Constant(false))();

  @override
  Set<Column> get primaryKey => {id};
}

@DataClassName('LocalConsultation')
class Consultations extends Table {
  TextColumn get id => text()();
  TextColumn get serverId => text().nullable()();
  TextColumn get patientId => text()();
  TextColumn get clinicId => text()();
  TextColumn get language => text().withDefault(const Constant('uz'))();
  TextColumn get chiefComplaint => text()();
  TextColumn get structuredSymptomsJson =>
      text().withDefault(const Constant('{}'))();
  TextColumn get vitalsJson => text().withDefault(const Constant('{}'))();
  TextColumn get status => text().withDefault(const Constant('draft'))();
  BoolColumn get createdOffline =>
      boolean().withDefault(const Constant(true))();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  DateTimeColumn get syncedAt => dateTime().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

@DataClassName('LocalSuggestion')
class Suggestions extends Table {
  TextColumn get id => text()();
  TextColumn get serverId => text().nullable()();
  TextColumn get consultationId => text()();
  TextColumn get payloadJson => text()();
  RealColumn get confidence => real().nullable()();
  TextColumn get model => text().withDefault(const Constant('unknown'))();
  BoolColumn get degraded => boolean().withDefault(const Constant(false))();

  /// Null until the clinician has accepted, edited or rejected it. The UI
  /// treats null as "gate still open" and will not mark the consultation done.
  TextColumn get decisionAction => text().nullable()();
  TextColumn get decisionText => text().nullable()();
  TextColumn get decisionReason => text().nullable()();
  DateTimeColumn get decidedAt => dateTime().nullable()();
  DateTimeColumn get createdAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

/// One row per pending server operation. Survives restarts and airplane mode.
@DataClassName('OutboxEntry')
class Outbox extends Table {
  TextColumn get operationId => text()();
  TextColumn get entityType => text()();
  TextColumn get op => text()();
  TextColumn get localId => text()();
  TextColumn get serverId => text().nullable()();
  TextColumn get payloadJson => text()();
  DateTimeColumn get updatedAt => dateTime()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  DateTimeColumn get nextAttemptAt => dateTime().nullable()();
  TextColumn get lastError => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();

  @override
  Set<Column> get primaryKey => {operationId};
}

/// Voice recordings waiting for a connection, so a feldsher can dictate with
/// no signal and have it transcribed later.
@DataClassName('PendingRecording')
class Recordings extends Table {
  TextColumn get id => text()();
  TextColumn get consultationId => text()();
  TextColumn get filePath => text()();
  TextColumn get language => text().withDefault(const Constant('uz'))();
  BoolColumn get uploaded => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

@DriftDatabase(
    tables: [Patients, Consultations, Suggestions, Outbox, Recordings])
class AppDatabase extends _$AppDatabase {
  AppDatabase(super.e);

  @override
  int get schemaVersion => 1;

  // --- patients ---------------------------------------------------------

  Future<List<LocalPatient>> searchPatients(String query) {
    if (query.trim().isEmpty) {
      return (select(patients)
            ..orderBy([(p) => OrderingTerm.desc(p.updatedAt)])
            ..limit(100))
          .get();
    }
    final String pattern = '%${query.trim()}%';
    return (select(patients)
          ..where((p) => p.mrn.like(pattern) | p.fullName.like(pattern))
          ..limit(100))
        .get();
  }

  Future<LocalPatient?> patientById(String id) =>
      (select(patients)..where((p) => p.id.equals(id))).getSingleOrNull();

  // --- consultations ----------------------------------------------------

  Future<List<LocalConsultation>> consultationsForPatient(String patientId) =>
      (select(consultations)
            ..where((c) => c.patientId.equals(patientId))
            ..orderBy([(c) => OrderingTerm.desc(c.createdAt)]))
          .get();

  Future<LocalConsultation?> consultationById(String id) =>
      (select(consultations)..where((c) => c.id.equals(id))).getSingleOrNull();

  Stream<int> watchPendingCount() =>
      (selectOnly(outbox)..addColumns([outbox.operationId.count()]))
          .map((row) => row.read(outbox.operationId.count()) ?? 0)
          .watchSingle();

  // --- outbox -----------------------------------------------------------

  /// Rows that are due now. A row with a future `nextAttemptAt` is backing off.
  Future<List<OutboxEntry>> dueOutboxEntries(DateTime now) => (select(outbox)
        ..where((o) =>
            o.nextAttemptAt.isSmallerOrEqualValue(now) |
            o.nextAttemptAt.isNull())
        ..orderBy([(o) => OrderingTerm.asc(o.createdAt)])
        ..limit(100))
      .get();

  Future<void> removeOutboxEntry(String operationId) =>
      (delete(outbox)..where((o) => o.operationId.equals(operationId))).go();

  /// Write the entity and its outbox row in one transaction.
  ///
  /// This is the invariant that makes "never lose a record" true: there is no
  /// window in which a consultation exists locally with nothing scheduled to
  /// send it.
  Future<void> saveConsultationWithOutbox({
    required ConsultationsCompanion consultation,
    required OutboxCompanion entry,
  }) {
    return transaction(() async {
      await into(consultations).insertOnConflictUpdate(consultation);
      await into(outbox).insertOnConflictUpdate(entry);
    });
  }

  Future<void> savePatientWithOutbox({
    required PatientsCompanion patient,
    required OutboxCompanion entry,
  }) {
    return transaction(() async {
      await into(patients).insertOnConflictUpdate(patient);
      await into(outbox).insertOnConflictUpdate(entry);
    });
  }

  Future<void> markConsultationSynced(String localId, String serverId) {
    return (update(consultations)..where((c) => c.id.equals(localId))).write(
      ConsultationsCompanion(
        serverId: Value(serverId),
        syncedAt: Value(DateTime.now().toUtc()),
      ),
    );
  }

  Future<void> markPatientSynced(String localId, String serverId) {
    return (update(patients)..where((p) => p.id.equals(localId))).write(
      PatientsCompanion(serverId: Value(serverId), synced: const Value(true)),
    );
  }
}

/// Small helpers so callers never hand-roll JSON encoding of map columns.
extension JsonColumns on Map<String, dynamic> {
  String toJsonColumn() => jsonEncode(this);
}

Map<String, dynamic> decodeJsonMap(String source) {
  if (source.trim().isEmpty) return <String, dynamic>{};
  final dynamic decoded = jsonDecode(source);
  return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
}

List<String> decodeJsonList(String source) {
  if (source.trim().isEmpty) return <String>[];
  final dynamic decoded = jsonDecode(source);
  return decoded is List
      ? decoded.map((e) => e.toString()).toList()
      : <String>[];
}
