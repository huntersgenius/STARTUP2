import 'package:flutter/material.dart';

import '../core/strings.dart';
import '../core/theme.dart';

enum DecisionAction { accept, edit, reject }

class DecisionResult {
  const DecisionResult({required this.action, this.finalText, this.reason});

  final DecisionAction action;
  final String? finalText;
  final String? reason;

  String get actionName => action.name;
}

/// The clinician-in-the-loop gate.
///
/// No suggestion is considered used until this returns. Edit requires text and
/// reject requires a reason — the same rules the server enforces, checked here
/// too so the clinician gets an immediate answer instead of a 400.
class DecisionGate extends StatefulWidget {
  const DecisionGate({
    super.key,
    required this.language,
    required this.onDecision,
    this.enabled = true,
  });

  final String language;
  final Future<void> Function(DecisionResult) onDecision;
  final bool enabled;

  @override
  State<DecisionGate> createState() => _DecisionGateState();
}

class _DecisionGateState extends State<DecisionGate> {
  final TextEditingController _controller = TextEditingController();
  DecisionAction? _pending;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit(DecisionAction action) async {
    final String text = _controller.text.trim();
    if (action == DecisionAction.edit && text.isEmpty) {
      setState(() {
        _pending = action;
        _error = tr('decision.editHint', widget.language);
      });
      return;
    }
    if (action == DecisionAction.reject && text.isEmpty) {
      setState(() {
        _pending = action;
        _error = tr('decision.reasonHint', widget.language);
      });
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await widget.onDecision(
        DecisionResult(
          action: action,
          finalText: action == DecisionAction.edit ? text : null,
          reason: action == DecisionAction.reject ? text : null,
        ),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool needsText =
        _pending == DecisionAction.edit || _pending == DecisionAction.reject;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        border: Border(top: BorderSide(color: Colors.grey.shade400, width: 2)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            tr('decision.required', widget.language),
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          if (needsText) ...<Widget>[
            const SizedBox(height: 12),
            TextField(
              key: const Key('decision-text'),
              controller: _controller,
              maxLines: 3,
              decoration: InputDecoration(
                hintText: _pending == DecisionAction.edit
                    ? tr('decision.editHint', widget.language)
                    : tr('decision.reasonHint', widget.language),
                errorText: _error,
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: <Widget>[
              Expanded(
                child: FilledButton.icon(
                  key: const Key('decision-accept'),
                  onPressed: widget.enabled && !_submitting
                      ? () => _submit(DecisionAction.accept)
                      : null,
                  icon: const Icon(Icons.check),
                  label: Text(tr('decision.accept', widget.language)),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppTheme.success,
                    minimumSize: const Size(0, AppTheme.touchTarget),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('decision-edit'),
                  onPressed: widget.enabled && !_submitting
                      ? () => _pending == DecisionAction.edit
                          ? _submit(DecisionAction.edit)
                          : setState(() => _pending = DecisionAction.edit)
                      : null,
                  icon: const Icon(Icons.edit),
                  label: Text(tr('decision.edit', widget.language)),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, AppTheme.touchTarget),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('decision-reject'),
                  onPressed: widget.enabled && !_submitting
                      ? () => _pending == DecisionAction.reject
                          ? _submit(DecisionAction.reject)
                          : setState(() => _pending = DecisionAction.reject)
                      : null,
                  icon: const Icon(Icons.close),
                  label: Text(tr('decision.reject', widget.language)),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppTheme.danger,
                    minimumSize: const Size(0, AppTheme.touchTarget),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
