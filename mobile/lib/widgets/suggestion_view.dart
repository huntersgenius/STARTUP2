import 'package:flutter/material.dart';

import '../core/strings.dart';
import '../core/theme.dart';
import '../data/models/suggestion.dart';
import 'disclaimer_bar.dart';
import 'red_flag_banner.dart';

/// Renders an AI suggestion.
///
/// Order on screen is fixed and is a safety property:
/// red flags → disclaimer → differentials → tests → treatment → referral.
/// The accept/edit/reject gate is rendered by the caller and is not optional.
class SuggestionView extends StatelessWidget {
  const SuggestionView({
    super.key,
    required this.suggestion,
    required this.language,
    this.degraded = false,
  });

  final ClinicalSuggestion suggestion;
  final String language;
  final bool degraded;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        RedFlagBannerList(flags: suggestion.redFlags, language: language),
        DisclaimerBar(language: language),
        if (degraded) ...<Widget>[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            color: Colors.amber.shade100,
            child: Text(
              tr('suggestion.offline', language),
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
          ),
        ],
        const SizedBox(height: 16),
        if (suggestion.insufficientData)
          _insufficient(context)
        else
          _differentials(context),
        if (suggestion.recommendedTests.isNotEmpty) ...<Widget>[
          _sectionTitle(tr('suggestion.tests', language)),
          for (final String test in suggestion.recommendedTests)
            ListTile(
              leading: const Icon(Icons.science_outlined),
              title: Text(test,
                  style: const TextStyle(fontSize: AppTheme.bodySize)),
            ),
        ],
        if (suggestion.treatmentItems.isNotEmpty ||
            suggestion.treatmentBlockedReason != null) ...<Widget>[
          _sectionTitle(tr('suggestion.treatment', language)),
          if (suggestion.treatmentBlockedReason == 'pediatric_weight_required')
            Container(
              key: const Key('pediatric-weight-block'),
              padding: const EdgeInsets.all(12),
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: AppTheme.dangerSurface,
                border: Border.all(color: AppTheme.danger),
              ),
              child: Text(
                tr('suggestion.pediatricWeight', language),
                style: const TextStyle(
                  fontSize: AppTheme.bodySize,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.danger,
                ),
              ),
            ),
          for (final TreatmentItem item in suggestion.treatmentItems)
            _treatmentTile(item),
          for (final String advice in suggestion.nonPharmacological)
            ListTile(
              leading: const Icon(Icons.check_circle_outline),
              title: Text(advice,
                  style: const TextStyle(fontSize: AppTheme.bodySize)),
            ),
        ],
        if (suggestion.referral.needed) ...<Widget>[
          _sectionTitle(tr('suggestion.referral', language)),
          Card(
            color: suggestion.referral.urgency == 'immediate'
                ? AppTheme.dangerSurface
                : null,
            child: ListTile(
              leading: const Icon(Icons.local_hospital_outlined, size: 32),
              title: Text(
                suggestion.referral.specialty ?? '',
                style: const TextStyle(
                    fontSize: AppTheme.bodySize, fontWeight: FontWeight.w700),
              ),
              subtitle: Text(
                suggestion.referral.reason ?? suggestion.referral.urgency,
                style: const TextStyle(fontSize: 16),
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _sectionTitle(String text) => Padding(
        padding: const EdgeInsets.only(top: 24, bottom: 8),
        child: Text(
          text,
          style: const TextStyle(
              fontSize: AppTheme.titleSize, fontWeight: FontWeight.w700),
        ),
      );

  Widget _insufficient(BuildContext context) => Column(
        key: const Key('insufficient-data'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            tr('suggestion.insufficient', language),
            style: const TextStyle(
                fontSize: AppTheme.titleSize, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 12),
          for (final String question in suggestion.followUpQuestions)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Text('• ',
                      style: TextStyle(fontSize: AppTheme.bodySize)),
                  Expanded(
                    child: Text(question,
                        style: const TextStyle(fontSize: AppTheme.bodySize)),
                  ),
                ],
              ),
            ),
        ],
      );

  Widget _differentials(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            tr('suggestion.title', language),
            style: const TextStyle(
                fontSize: AppTheme.titleSize, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          for (final Differential d in suggestion.differentials)
            Card(
              key: Key('differential-${d.condition}'),
              margin: const EdgeInsets.symmetric(vertical: 6),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Expanded(
                          child: Text(
                            d.condition,
                            style: const TextStyle(
                                fontSize: 20, fontWeight: FontWeight.w700),
                          ),
                        ),
                        if (d.icd10 != null)
                          Chip(
                              label: Text(d.icd10!,
                                  style: const TextStyle(fontSize: 14))),
                      ],
                    ),
                    const SizedBox(height: 8),
                    // A band, never a percentage.
                    //
                    // The underlying number is not a probability. On the rules
                    // path it is a normalised vote from a lookup table; on the
                    // model path it is whatever the model wrote. Measured
                    // calibration error is 0.28, and on text outside the
                    // terminology map the signal trends the wrong way — higher
                    // scores were *less* often correct. Printing "62%" invites
                    // a clinician to read it as "62% likely", which it is not.
                    // See docs/EVAL_INTEGRITY.md.
                    LinearProgressIndicator(
                      value: d.confidence.clamp(0, 1),
                      minHeight: 12,
                      backgroundColor: Colors.grey.shade300,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      matchBandLabel(d.confidence, language),
                      key: Key('match-band-${d.condition}'),
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '${tr('suggestion.why', language)}: ${d.why}',
                      style: const TextStyle(fontSize: AppTheme.bodySize),
                    ),
                    if (d.citations.isNotEmpty) ...<Widget>[
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 6,
                        children: <Widget>[
                          for (final String citation in d.citations)
                            Chip(
                              avatar: const Icon(Icons.menu_book_outlined,
                                  size: 18),
                              label: Text(citation,
                                  style: const TextStyle(fontSize: 13)),
                            ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
        ],
      );

  Widget _treatmentTile(TreatmentItem item) {
    final bool unavailable = !item.isAvailable;
    return Card(
      key: Key('treatment-${item.drug}'),
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: ListTile(
        leading: Icon(
          unavailable ? Icons.error_outline : Icons.medication_outlined,
          color: unavailable ? AppTheme.warning : null,
          size: 32,
        ),
        title: Text(
          <String?>[item.drug, item.dose, item.duration]
              .whereType<String>()
              .join(' · '),
          style: const TextStyle(
              fontSize: AppTheme.bodySize, fontWeight: FontWeight.w600),
        ),
        subtitle: unavailable
            ? Text(
                <String?>[
                  tr('suggestion.notAvailable', language),
                  if (item.substitute != null)
                    '${tr('suggestion.substitute', language)}: ${item.substitute}',
                  item.notes,
                ].whereType<String>().join('\n'),
                style: const TextStyle(fontSize: 16, color: AppTheme.warning),
              )
            : (item.notes != null
                ? Text(item.notes!, style: const TextStyle(fontSize: 16))
                : null),
      ),
    );
  }
}
