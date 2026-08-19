import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../data/local/database.dart';
import '../../data/models/suggestion.dart';
import '../../data/remote/api_client.dart';
import '../../providers.dart';
import '../../widgets/decision_gate.dart';
import '../../widgets/disclaimer_bar.dart';
import '../../widgets/suggestion_view.dart';
import 'offline_engine.dart';
import 'symptom_matcher.dart';

/// Symptom entry → assessment → decision, on one screen.
///
/// A feldsher standing between patients should not be navigating a wizard.
/// Everything needed for one consultation is here, in the order the visit
/// actually happens.
class ConsultationScreen extends ConsumerStatefulWidget {
  const ConsultationScreen({
    super.key,
    required this.patient,
    this.onRecordVoice,
  });

  final LocalPatient patient;

  /// Injected so tests can drive voice input without a microphone.
  final Future<String?> Function()? onRecordVoice;

  @override
  ConsumerState<ConsultationScreen> createState() => _ConsultationScreenState();
}

class _ConsultationScreenState extends ConsumerState<ConsultationScreen> {
  final TextEditingController _complaint = TextEditingController();
  final Map<String, TextEditingController> _vitals =
      <String, TextEditingController>{
    'temperature_c': TextEditingController(),
    'pulse_bpm': TextEditingController(),
    'systolic_bp': TextEditingController(),
    'diastolic_bp': TextEditingController(),
    'respiratory_rate': TextEditingController(),
    'spo2': TextEditingController(),
    'weight_kg': TextEditingController(),
    'glucose_mmol': TextEditingController(),
  };
  final Set<String> _selected = <String>{};

  ClinicalSuggestion? _suggestion;
  LocalSuggestion? _storedSuggestion;
  LocalConsultation? _consultation;
  bool _busy = false;
  bool _degraded = false;
  bool _decided = false;
  String? _error;
  bool _recording = false;

  @override
  void dispose() {
    _complaint.dispose();
    for (final TextEditingController c in _vitals.values) {
      c.dispose();
    }
    super.dispose();
  }

  Map<String, dynamic> _collectVitals() {
    final Map<String, dynamic> out = <String, dynamic>{};
    _vitals.forEach((String key, TextEditingController controller) {
      final String text = controller.text.trim().replaceAll(',', '.');
      if (text.isEmpty) return;
      final num? value = num.tryParse(text);
      if (value != null) out[key] = value;
    });
    return out;
  }

  double? get _ageYears {
    final DateTime? dob = widget.patient.dob;
    if (dob == null) return null;
    return DateTime.now().difference(dob).inDays / 365.25;
  }

  Future<void> _analyze() async {
    final String language = ref.read(languageProvider);
    if (_complaint.text.trim().length < 2 && _selected.isEmpty) {
      setState(() => _error = tr('consultation.complaintHint', language));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });

    final Map<String, dynamic> vitals = _collectVitals();
    try {
      // The consultation is saved locally before anything is attempted over
      // the network, so a failure here cannot lose the visit.
      final LocalConsultation consultation =
          await ref.read(repositoryProvider).createConsultation(
                patientId: widget.patient.id,
                clinicId: widget.patient.clinicId,
                chiefComplaint: _complaint.text.trim(),
                language: language,
                structuredSymptoms: <String, dynamic>{
                  'concepts': _selected.toList(),
                },
                vitals: vitals,
              );
      _consultation = consultation;

      try {
        final LocalSuggestion stored =
            await ref.read(repositoryProvider).analyze(consultation);
        setState(() {
          _storedSuggestion = stored;
          _suggestion = ClinicalSuggestion.fromJsonString(stored.payloadJson);
          _degraded = stored.degraded;
        });
      } on ApiException catch (e) {
        if (!e.transient) rethrow;
        // No server: fall back to the deterministic layer, which is the part
        // that catches the dangerous cases anyway.
        setState(() {
          _suggestion = const OfflineEngine().assess(
            freeText: _complaint.text,
            selectedConcepts: _selected,
            vitals: vitals,
            ageYears: _ageYears,
            language: language,
          );
          _degraded = true;
        });
      }
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _decide(DecisionResult result) async {
    final LocalSuggestion? stored = _storedSuggestion;
    if (stored != null) {
      await ref.read(repositoryProvider).recordDecision(
            suggestion: stored,
            action: result.actionName,
            finalText: result.finalText,
            reason: result.reason,
          );
    }
    if (mounted) setState(() => _decided = true);
  }

  Future<void> _record() async {
    final Future<String?> Function()? recorder = widget.onRecordVoice;
    if (recorder == null) return;
    setState(() => _recording = true);
    try {
      final String? transcript = await recorder();
      if (transcript != null && transcript.isNotEmpty) {
        _complaint.text = <String>[_complaint.text.trim(), transcript]
            .where((s) => s.isNotEmpty)
            .join(' ');
      }
    } finally {
      if (mounted) setState(() => _recording = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final String language = ref.watch(languageProvider);
    final ClinicalSuggestion? suggestion = _suggestion;

    return Scaffold(
      appBar: AppBar(
        title:
            Text('${tr('consultation.new', language)} · ${widget.patient.mrn}'),
        // Saved-locally is shown as soon as the record exists, before any
        // network call — that is the reassurance a feldsher actually needs.
        actions: <Widget>[
          if (_consultation != null)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Row(
                children: <Widget>[
                  const Icon(Icons.save_outlined, size: 22),
                  const SizedBox(width: 6),
                  Text(
                    _consultation!.syncedAt != null
                        ? tr('sync.allSent', language)
                        : tr('sync.pending', language),
                    style: const TextStyle(fontSize: 14),
                  ),
                ],
              ),
            ),
        ],
      ),
      body: suggestion == null
          ? _entryForm(language)
          : Column(
              children: <Widget>[
                Expanded(
                  child: SuggestionView(
                    suggestion: suggestion,
                    language: language,
                    degraded: _degraded,
                  ),
                ),
                if (!_decided)
                  DecisionGate(language: language, onDecision: _decide)
                else
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      tr('common.done', language),
                      key: const Key('decision-recorded'),
                      style: const TextStyle(
                        fontSize: AppTheme.bodySize,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.success,
                      ),
                    ),
                  ),
              ],
            ),
    );
  }

  Widget _entryForm(String language) {
    return Column(
      children: <Widget>[
        DisclaimerBar(language: language),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: <Widget>[
              Text(
                tr('consultation.complaint', language),
                style: const TextStyle(
                    fontSize: AppTheme.titleSize, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              TextField(
                key: const Key('complaint-field'),
                controller: _complaint,
                maxLines: 4,
                style: const TextStyle(fontSize: AppTheme.bodySize),
                decoration: InputDecoration(
                  hintText: tr('consultation.complaintHint', language),
                  errorText: _error,
                ),
              ),
              const SizedBox(height: 12),
              if (widget.onRecordVoice != null)
                OutlinedButton.icon(
                  key: const Key('mic-button'),
                  onPressed: _recording ? null : _record,
                  icon: Icon(_recording ? Icons.mic : Icons.mic_none, size: 28),
                  label: Text(
                    _recording
                        ? tr('consultation.recording', language)
                        : tr('consultation.mic', language),
                  ),
                ),
              const SizedBox(height: 24),
              Text(
                tr('consultation.symptoms', language),
                style: const TextStyle(
                    fontSize: AppTheme.titleSize, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: <Widget>[
                  for (final String concept in kSymptomChips)
                    FilterChip(
                      key: Key('chip-$concept'),
                      label: Text(conceptLabel(concept, language)),
                      selected: _selected.contains(concept),
                      onSelected: (bool on) => setState(() {
                        if (on) {
                          _selected.add(concept);
                        } else {
                          _selected.remove(concept);
                        }
                      }),
                    ),
                ],
              ),
              const SizedBox(height: 24),
              Text(
                tr('consultation.vitals', language),
                style: const TextStyle(
                    fontSize: AppTheme.titleSize, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              for (final MapEntry<String, String> field in <String, String>{
                'temperature_c': 'vitals.temperature',
                'pulse_bpm': 'vitals.pulse',
                'systolic_bp': 'vitals.systolic',
                'diastolic_bp': 'vitals.diastolic',
                'respiratory_rate': 'vitals.respiratory',
                'spo2': 'vitals.spo2',
                'weight_kg': 'vitals.weight',
                'glucose_mmol': 'vitals.glucose',
              }.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: TextField(
                    key: Key('vital-${field.key}'),
                    controller: _vitals[field.key],
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    style: const TextStyle(fontSize: AppTheme.bodySize),
                    decoration:
                        InputDecoration(labelText: tr(field.value, language)),
                  ),
                ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: FilledButton.icon(
            key: const Key('analyze-button'),
            onPressed: _busy ? null : _analyze,
            icon: _busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.psychology_outlined),
            label: Text(tr('consultation.analyze', language)),
          ),
        ),
      ],
    );
  }
}
