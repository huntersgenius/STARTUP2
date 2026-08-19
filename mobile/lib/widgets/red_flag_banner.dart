import 'package:flutter/material.dart';

import '../core/strings.dart';
import '../core/theme.dart';
import '../data/models/suggestion.dart';

/// Red flags render above everything else, in red, unmissable.
///
/// Placement is a safety property, not a style choice: a clinician scanning a
/// screen between patients must see "refer now" before they see a
/// differential list they might act on instead.
class RedFlagBannerList extends StatelessWidget {
  const RedFlagBannerList({
    super.key,
    required this.flags,
    required this.language,
  });

  final List<RedFlagBanner> flags;
  final String language;

  @override
  Widget build(BuildContext context) {
    if (flags.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        for (final RedFlagBanner flag in flags)
          Container(
            key: Key('red-flag-${flag.code}'),
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppTheme.dangerSurface,
              border: Border.all(color: AppTheme.danger, width: 3),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const Icon(Icons.warning_amber_rounded,
                    color: AppTheme.danger, size: 40),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        tr('redflag.banner', language),
                        style: const TextStyle(
                          color: AppTheme.danger,
                          fontSize: AppTheme.titleSize,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        flag.message,
                        style: const TextStyle(fontSize: AppTheme.bodySize),
                      ),
                      if (flag.isImmediate) ...<Widget>[
                        const SizedBox(height: 8),
                        Text(
                          tr('redflag.referNow', language),
                          style: const TextStyle(
                            fontSize: AppTheme.bodySize,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.danger,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
