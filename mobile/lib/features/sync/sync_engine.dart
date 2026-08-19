import 'dart:convert';

import 'package:drift/drift.dart';

import '../../core/constants.dart';
import '../../data/local/database.dart';
import '../../data/remote/api_client.dart';

/// Result of one sync pass, in terms a non-technical user can be shown.
class SyncOutcome {
  const SyncOutcome({
    required this.attempted,
    required this.applied,
    required this.duplicates,
    required this.rejected,
    required this.stillPending,
    this.error,
  });

  final int attempted;
  final int applied;
  final int duplicates;
  final int rejected;
  final int stillPending;
  final String? error;

  bool get isSuccess => error == null && rejected == 0;

  static const SyncOutcome idle = SyncOutcome(
    attempted: 0,
    applied: 0,
    duplicates: 0,
    rejected: 0,
    stillPending: 0,
  );
}

/// Drains the outbox.
///
/// Invariants this class exists to protect:
///
/// 1. **An outbox row is deleted only after the server confirms it.** A crash
///    mid-sync leaves the row, and the operation is replayed. The server is
///    idempotent on `operation_id`, so a replay is free.
/// 2. **A transient failure never discards work.** It schedules a backoff.
/// 3. **A permanent failure does not retry forever.** After the backoff table
///    is exhausted the row is kept and surfaced to the user, because deleting
///    it would silently lose a patient record.
class SyncEngine {
  SyncEngine({
    required AppDatabase db,
    required ApiClient api,
    required String deviceId,
    DateTime Function() now = DateTime.now,
  })  : _db = db,
        _api = api,
        _deviceId = deviceId,
        _now = now;

  final AppDatabase _db;
  final ApiClient _api;
  final String _deviceId;
  final DateTime Function() _now;

  Future<int> pendingCount() async {
    final List<OutboxEntry> all = await _db.select(_db.outbox).get();
    return all.length;
  }

  /// Drain the outbox, parents before children.
  ///
  /// A patient and their first consultation are usually created seconds apart
  /// offline, so both are due in the same pass. The consultation's payload
  /// still carries the patient's *local* id at that point, and the server has
  /// never seen it — sending them together gets the consultation rejected as
  /// an orphan. Patients are therefore sent first; confirming them rewrites
  /// the pending consultation payloads, and the second phase sends those.
  Future<SyncOutcome> syncOnce() async {
    final DateTime now = _now();
    final List<OutboxEntry> allDue = await _db.dueOutboxEntries(now);
    final List<OutboxEntry> parents =
        allDue.where((e) => e.entityType == 'patient').toList();

    if (parents.isNotEmpty) {
      final SyncOutcome parentOutcome = await _sendBatch(parents);
      if (parentOutcome.error != null) {
        return parentOutcome;
      }
      final List<OutboxEntry> children = await _db.dueOutboxEntries(_now());
      final SyncOutcome childOutcome = await _sendBatch(
        children.where((e) => e.entityType != 'patient').toList(),
      );
      return SyncOutcome(
        attempted: parentOutcome.attempted + childOutcome.attempted,
        applied: parentOutcome.applied + childOutcome.applied,
        duplicates: parentOutcome.duplicates + childOutcome.duplicates,
        rejected: parentOutcome.rejected + childOutcome.rejected,
        stillPending: await pendingCount(),
        error: childOutcome.error,
      );
    }

    return _sendBatch(allDue);
  }

  Future<SyncOutcome> _sendBatch(List<OutboxEntry> due) async {
    if (due.isEmpty) {
      return SyncOutcome(
        attempted: 0,
        applied: 0,
        duplicates: 0,
        rejected: 0,
        stillPending: await pendingCount(),
      );
    }

    final List<Map<String, dynamic>> operations = due
        .map((OutboxEntry e) => <String, dynamic>{
              'operation_id': e.operationId,
              'entity_type': e.entityType,
              'op': e.op,
              if (e.serverId != null) 'server_id': e.serverId,
              'updated_at': e.updatedAt.toUtc().toIso8601String(),
              'data': jsonDecode(e.payloadJson),
            })
        .toList();

    List<Map<String, dynamic>> results;
    try {
      results = await _api.sync(deviceId: _deviceId, operations: operations);
    } on ApiException catch (e) {
      // The whole batch failed. Nothing is deleted; every row backs off.
      for (final OutboxEntry entry in due) {
        await _backOff(entry, e.message);
      }
      return SyncOutcome(
        attempted: due.length,
        applied: 0,
        duplicates: 0,
        rejected: 0,
        stillPending: await pendingCount(),
        error: e.message,
      );
    }

    int applied = 0;
    int duplicates = 0;
    int rejected = 0;
    final Map<String, OutboxEntry> byId = <String, OutboxEntry>{
      for (final OutboxEntry e in due) e.operationId: e,
    };

    for (final Map<String, dynamic> result in results) {
      final String operationId = result['operation_id'].toString();
      final String status = result['status'].toString();
      final OutboxEntry? entry = byId[operationId];
      if (entry == null) continue;

      switch (status) {
        case 'applied':
        case 'conflict_merged':
          applied++;
          await _confirm(entry, result['server_id']?.toString());
          break;
        case 'duplicate':
          // The server already has it; the row has done its job.
          duplicates++;
          await _confirm(entry, result['server_id']?.toString());
          break;
        default:
          rejected++;
          await _backOff(entry, result['detail']?.toString() ?? 'rejected');
      }
    }

    return SyncOutcome(
      attempted: due.length,
      applied: applied,
      duplicates: duplicates,
      rejected: rejected,
      stillPending: await pendingCount(),
    );
  }

  Future<void> _confirm(OutboxEntry entry, String? serverId) async {
    if (serverId != null) {
      if (entry.entityType == 'consultation') {
        await _db.markConsultationSynced(entry.localId, serverId);
      } else if (entry.entityType == 'patient') {
        await _db.markPatientSynced(entry.localId, serverId);
        // Consultations queued against a local patient id need the server id
        // before they can be accepted.
        await _rewritePatientReferences(entry.localId, serverId);
      }
    }
    await _db.removeOutboxEntry(entry.operationId);
  }

  /// A consultation created offline references the patient's *local* id. Once
  /// the patient exists on the server, pending consultations must point at the
  /// server id or they will be rejected as orphans.
  Future<void> _rewritePatientReferences(
      String localPatientId, String serverPatientId) async {
    final List<OutboxEntry> pending = await _db.select(_db.outbox).get();
    for (final OutboxEntry entry in pending) {
      if (entry.entityType != 'consultation') continue;
      final Map<String, dynamic> payload =
          (jsonDecode(entry.payloadJson) as Map).cast<String, dynamic>();
      if (payload['patient_id'] != localPatientId) continue;
      payload['patient_id'] = serverPatientId;
      await (_db.update(_db.outbox)
            ..where((o) => o.operationId.equals(entry.operationId)))
          .write(OutboxCompanion(payloadJson: Value(jsonEncode(payload))));
    }
  }

  Future<void> _backOff(OutboxEntry entry, String error) async {
    final int attempts = entry.attempts + 1;
    final Duration delay = attempts <= kRetryBackoff.length
        ? kRetryBackoff[attempts - 1]
        : kRetryBackoff.last;
    await (_db.update(_db.outbox)
          ..where((o) => o.operationId.equals(entry.operationId)))
        .write(
      OutboxCompanion(
        attempts: Value(attempts),
        // The row is never deleted on failure. A patient record that cannot
        // be sent is a support problem, not a reason to lose it.
        nextAttemptAt: Value(_now().add(delay)),
        lastError: Value(error),
      ),
    );
  }
}
