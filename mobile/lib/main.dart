import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import 'core/strings.dart';
import 'core/theme.dart';
import 'data/local/database.dart';
import 'features/auth/login_screen.dart';
import 'features/patients/patient_list_screen.dart';
import 'providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final AppDatabase database = await openDatabase();

  runApp(
    ProviderScope(
      overrides: <Override>[
        databaseProvider.overrideWithValue(database),
        // A per-install identifier so the server can attribute sync
        // operations to a device without any hardware identifier.
        deviceIdProvider.overrideWithValue(const Uuid().v4()),
      ],
      child: const SihhatApp(),
    ),
  );
}

class SihhatApp extends ConsumerStatefulWidget {
  const SihhatApp({super.key});

  @override
  ConsumerState<SihhatApp> createState() => _SihhatAppState();
}

class _SihhatAppState extends ConsumerState<SihhatApp> {
  bool _signedIn = false;

  @override
  Widget build(BuildContext context) {
    final String language = ref.watch(languageProvider);
    return MaterialApp(
      title: tr('app.title', language),
      theme: AppTheme.light(),
      debugShowCheckedModeBanner: false,
      home: _signedIn
          ? const PatientListScreen()
          : LoginScreen(onSignedIn: () => setState(() => _signedIn = true)),
    );
  }
}
