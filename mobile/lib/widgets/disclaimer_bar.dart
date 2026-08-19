import 'package:flutter/material.dart';

import '../core/strings.dart';

/// The clinician-in-the-loop notice.
///
/// Present on every screen that shows AI output. Not dismissible: a notice a
/// user can turn off is a notice that is off.
class DisclaimerBar extends StatelessWidget {
  const DisclaimerBar({super.key, required this.language, this.long = false});

  final String language;
  final bool long;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Container(
      key: const Key('disclaimer-bar'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      color: theme.colorScheme.secondaryContainer,
      child: Row(
        children: <Widget>[
          Icon(Icons.info_outline,
              color: theme.colorScheme.onSecondaryContainer),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              tr(long ? 'disclaimer.long' : 'disclaimer.short', language),
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: theme.colorScheme.onSecondaryContainer,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
