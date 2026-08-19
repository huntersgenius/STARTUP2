import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../data/remote/api_client.dart';
import '../../providers.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key, required this.onSignedIn});

  final VoidCallback onSignedIn;

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final TextEditingController _email = TextEditingController();
  final TextEditingController _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final String language = ref.read(languageProvider);
    try {
      final TokenPair tokens = await ref
          .read(apiClientProvider)
          .login(_email.text.trim(), _password.text);
      ref.read(apiClientProvider).setAccessToken(tokens.accessToken);
      await ref
          .read(secureStorageProvider)
          .write(key: 'refresh_token', value: tokens.refreshToken);
      widget.onSignedIn();
    } on ApiException {
      setState(() => _error = tr('login.error', language));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final String language = ref.watch(languageProvider);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.all(24),
              children: <Widget>[
                Text(
                  tr('app.title', language),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 40, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 8),
                const LanguageToggle(),
                const SizedBox(height: 32),
                TextField(
                  key: const Key('login-email'),
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autocorrect: false,
                  style: const TextStyle(fontSize: AppTheme.bodySize),
                  decoration:
                      InputDecoration(labelText: tr('login.email', language)),
                ),
                const SizedBox(height: 16),
                TextField(
                  key: const Key('login-password'),
                  controller: _password,
                  obscureText: true,
                  style: const TextStyle(fontSize: AppTheme.bodySize),
                  decoration: InputDecoration(
                    labelText: tr('login.password', language),
                    errorText: _error,
                  ),
                ),
                const SizedBox(height: 24),
                FilledButton(
                  key: const Key('login-submit'),
                  onPressed: _busy ? null : _submit,
                  child: Text(tr('login.submit', language)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// One tap between Uzbek and Russian, reachable from every screen.
class LanguageToggle extends ConsumerWidget {
  const LanguageToggle({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final String language = ref.watch(languageProvider);
    return SegmentedButton<String>(
      key: const Key('language-toggle'),
      segments: const <ButtonSegment<String>>[
        ButtonSegment<String>(value: 'uz', label: Text('O\'zbekcha')),
        ButtonSegment<String>(value: 'ru', label: Text('Русский')),
      ],
      selected: <String>{language},
      onSelectionChanged: (Set<String> selection) =>
          ref.read(languageProvider.notifier).state = selection.first,
    );
  }
}
