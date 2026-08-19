import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/strings.dart';
import '../core/theme.dart';

/// Sync status, written for a feldsher rather than an engineer.
///
/// Three things and no more: how many records are waiting, when it last
/// worked, and a button to try again. No spinners without numbers, no jargon,
/// no silent failure — an unsent record must always be visible as a count.
class SyncIndicator extends StatelessWidget {
  const SyncIndicator({
    super.key,
    required this.language,
    required this.pendingCount,
    required this.isOnline,
    required this.isSyncing,
    this.lastSyncedAt,
    this.onRetry,
  });

  final String language;
  final int pendingCount;
  final bool isOnline;
  final bool isSyncing;
  final DateTime? lastSyncedAt;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final bool allSent = pendingCount == 0;
    final Color background = !isOnline
        ? AppTheme.offline
        : allSent
            ? AppTheme.success
            : AppTheme.warning;

    final String headline = isSyncing
        ? tr('sync.syncing', language)
        : !isOnline
            ? tr('sync.offline', language)
            : allSent
                ? tr('sync.allSent', language)
                : '${tr('sync.pending', language)}: $pendingCount';

    return Material(
      color: background,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: <Widget>[
            Icon(
              !isOnline
                  ? Icons.cloud_off
                  : allSent
                      ? Icons.cloud_done
                      : Icons.cloud_upload,
              color: Colors.white,
              size: 28,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    headline,
                    key: const Key('sync-headline'),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  Text(
                    '${tr('sync.lastSynced', language)}: ${_formatLastSync(language)}',
                    style: const TextStyle(color: Colors.white, fontSize: 14),
                  ),
                ],
              ),
            ),
            if (!allSent && !isSyncing && onRetry != null)
              TextButton(
                key: const Key('sync-retry'),
                onPressed: onRetry,
                style: TextButton.styleFrom(
                  foregroundColor: Colors.white,
                  minimumSize: const Size(96, AppTheme.touchTarget),
                ),
                child: Text(tr('sync.retry', language)),
              ),
          ],
        ),
      ),
    );
  }

  String _formatLastSync(String language) {
    if (lastSyncedAt == null) return tr('sync.never', language);
    return DateFormat('dd.MM HH:mm').format(lastSyncedAt!.toLocal());
  }
}
