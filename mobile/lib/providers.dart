import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'data/local/database.dart';
import 'data/remote/api_client.dart';
import 'data/repository.dart';
import 'features/sync/sync_engine.dart';

/// Base URL of the clinic's server. On an edge deployment this points at the
/// mini-PC in the clinic; otherwise at the cloud API.
final Provider<String> baseUrlProvider = Provider<String>((Ref ref) {
  return const String.fromEnvironment(
    'SIHHAT_API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );
});

final Provider<AppDatabase> databaseProvider = Provider<AppDatabase>((Ref ref) {
  throw UnimplementedError('databaseProvider must be overridden at startup');
});

final Provider<Dio> dioProvider = Provider<Dio>((Ref ref) {
  return Dio(
    BaseOptions(
      baseUrl: ref.watch(baseUrlProvider),
      // Short timeouts: a clinician must find out quickly that the network is
      // gone so the app can fall back, not sit on a spinner.
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 20),
      sendTimeout: const Duration(seconds: 20),
    ),
  );
});

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((Ref ref) {
  return ApiClient(dio: ref.watch(dioProvider));
});

final Provider<FlutterSecureStorage> secureStorageProvider =
    Provider<FlutterSecureStorage>((Ref ref) => const FlutterSecureStorage());

final Provider<ClinicalRepository> repositoryProvider =
    Provider<ClinicalRepository>((Ref ref) {
  return ClinicalRepository(
    db: ref.watch(databaseProvider),
    api: ref.watch(apiClientProvider),
  );
});

final Provider<SyncEngine> syncEngineProvider = Provider<SyncEngine>((Ref ref) {
  return SyncEngine(
    db: ref.watch(databaseProvider),
    api: ref.watch(apiClientProvider),
    deviceId: ref.watch(deviceIdProvider),
  );
});

final Provider<String> deviceIdProvider = Provider<String>((Ref ref) {
  throw UnimplementedError('deviceIdProvider must be overridden at startup');
});

/// Uzbek by default, switchable with one tap.
final StateProvider<String> languageProvider =
    StateProvider<String>((Ref ref) => 'uz');

final StreamProvider<bool> connectivityProvider =
    StreamProvider<bool>((Ref ref) async* {
  final Connectivity connectivity = Connectivity();
  yield !(await connectivity.checkConnectivity())
      .contains(ConnectivityResult.none);
  await for (final List<ConnectivityResult> status
      in connectivity.onConnectivityChanged) {
    yield !status.contains(ConnectivityResult.none);
  }
});

final StreamProvider<int> pendingSyncProvider = StreamProvider<int>(
    (Ref ref) => ref.watch(databaseProvider).watchPendingCount());

/// Opens the on-device database. Called once at startup.
///
/// The device is the record of truth while offline, so the file lives in
/// app-private storage and is never cleared by the app itself.
Future<AppDatabase> openDatabase() async {
  final Directory dir = await getApplicationDocumentsDirectory();
  return AppDatabase(
    LazyDatabase(() async {
      final File file = File(p.join(dir.path, 'sihhatai.sqlite'));
      return NativeDatabase.createInBackground(file);
    }),
  );
}

/// In-memory database for tests and widget previews.
AppDatabase openInMemoryDatabase() => AppDatabase(NativeDatabase.memory());
