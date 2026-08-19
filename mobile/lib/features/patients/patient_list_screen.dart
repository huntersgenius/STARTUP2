import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../data/local/database.dart';
import '../../providers.dart';
import '../../widgets/sync_indicator.dart';
import '../auth/login_screen.dart';
import '../consultation/consultation_screen.dart';

class PatientListScreen extends ConsumerStatefulWidget {
  const PatientListScreen({super.key});

  @override
  ConsumerState<PatientListScreen> createState() => _PatientListScreenState();
}

class _PatientListScreenState extends ConsumerState<PatientListScreen> {
  final TextEditingController _search = TextEditingController();
  List<LocalPatient> _results = <LocalPatient>[];
  DateTime? _lastSynced;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    // Reading from the local database means the list works with no signal.
    unawaited(_load());
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final List<LocalPatient> rows =
        await ref.read(databaseProvider).searchPatients(_search.text);
    if (mounted) setState(() => _results = rows);
  }

  Future<void> _sync() async {
    setState(() => _syncing = true);
    try {
      final outcome = await ref.read(syncEngineProvider).syncOnce();
      if (mounted && outcome.isSuccess) {
        setState(() => _lastSynced = DateTime.now());
      }
    } finally {
      if (mounted) setState(() => _syncing = false);
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final String language = ref.watch(languageProvider);
    final int pending = ref.watch(pendingSyncProvider).value ?? 0;
    final bool online = ref.watch(connectivityProvider).value ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(tr('patients.title', language)),
        actions: const <Widget>[
          Padding(padding: EdgeInsets.only(right: 12), child: LanguageToggle()),
        ],
      ),
      body: Column(
        children: <Widget>[
          SyncIndicator(
            language: language,
            pendingCount: pending,
            isOnline: online,
            isSyncing: _syncing,
            lastSyncedAt: _lastSynced,
            onRetry: _sync,
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              key: const Key('patient-search'),
              controller: _search,
              onChanged: (_) => unawaited(_load()),
              style: const TextStyle(fontSize: AppTheme.bodySize),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                labelText: tr('patients.search', language),
              ),
            ),
          ),
          Expanded(
            child: _results.isEmpty
                ? Center(
                    child: Text(
                      tr('patients.empty', language),
                      style: const TextStyle(fontSize: AppTheme.bodySize),
                    ),
                  )
                : ListView.separated(
                    itemCount: _results.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (BuildContext context, int index) {
                      final LocalPatient patient = _results[index];
                      return ListTile(
                        key: Key('patient-${patient.id}'),
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 12),
                        leading: CircleAvatar(
                          radius: 28,
                          child: Text(
                            patient.fullName.characters.first.toUpperCase(),
                            style: const TextStyle(fontSize: 22),
                          ),
                        ),
                        title: Text(
                          patient.fullName,
                          style: const TextStyle(
                              fontSize: AppTheme.bodySize,
                              fontWeight: FontWeight.w600),
                        ),
                        subtitle: Text(
                          patient.mrn,
                          style: const TextStyle(fontSize: 16),
                        ),
                        trailing: patient.synced
                            ? const Icon(Icons.cloud_done,
                                color: AppTheme.success)
                            : const Icon(Icons.cloud_upload,
                                color: AppTheme.warning),
                        onTap: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) =>
                                ConsultationScreen(patient: patient),
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('new-patient'),
        onPressed: () => _showNewPatientSheet(context, language),
        icon: const Icon(Icons.person_add_alt),
        label: Text(tr('patients.new', language)),
      ),
    );
  }

  Future<void> _showNewPatientSheet(
      BuildContext context, String language) async {
    final TextEditingController name = TextEditingController();
    final TextEditingController phone = TextEditingController();

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext sheetContext) => Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            TextField(
              key: const Key('new-patient-name'),
              controller: name,
              style: const TextStyle(fontSize: AppTheme.bodySize),
              decoration: const InputDecoration(labelText: 'F.I.SH.'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: phone,
              keyboardType: TextInputType.phone,
              style: const TextStyle(fontSize: AppTheme.bodySize),
              decoration: const InputDecoration(labelText: 'Telefon'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('new-patient-save'),
              onPressed: () async {
                if (name.text.trim().length < 2) return;
                await ref.read(repositoryProvider).createPatient(
                      clinicId: 'local-clinic',
                      fullName: name.text.trim(),
                      phone:
                          phone.text.trim().isEmpty ? null : phone.text.trim(),
                    );
                if (sheetContext.mounted) Navigator.of(sheetContext).pop();
              },
              child: Text(tr('common.save', language)),
            ),
          ],
        ),
      ),
    );
    name.dispose();
    phone.dispose();
    await _load();
  }
}
