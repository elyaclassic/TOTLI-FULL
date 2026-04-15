import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'screens/login_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/consent_screen.dart';
import 'services/session_service.dart';
import 'services/api_service.dart';
import 'services/sync_service.dart';

// Joriy ilova versiyasi
const String appVersion = '2.0.2';
const int appBuild = 49;

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  runApp(const TotliApp());
}

class TotliApp extends StatelessWidget {
  const TotliApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TOTLI HOLVA',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF017449),
          primary: const Color(0xFF017449),
          secondary: const Color(0xFFFFB50D),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
      ),
      home: const SplashScreen(),
    );
  }
}

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  String _statusText = '';

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    await Future.delayed(const Duration(milliseconds: 500));
    if (!mounted) return;

    final session = SessionService();
    final savedUrl = await session.getApiUrl();
    if (savedUrl != null && savedUrl.isNotEmpty) {
      ApiService.setBaseUrl(savedUrl);
    }

    // Yangilash tekshirish
    setState(() => _statusText = 'Yangilanish tekshirilmoqda...');
    try {
      final versionInfo = await ApiService.checkAppVersion();
      if (versionInfo.isNotEmpty && mounted) {
        final serverBuild = versionInfo['build'] ?? 0;
        final serverVersion = versionInfo['version'] ?? '';
        final forceUpdate = versionInfo['force_update'] == true;
        final downloadUrl = versionInfo['download_url'] ?? '';
        final changelog = versionInfo['changelog'] ?? '';

        if (serverBuild > appBuild && downloadUrl.isNotEmpty) {
          // Yangi versiya bor
          final shouldUpdate = await _showUpdateDialog(
            serverVersion: serverVersion,
            changelog: changelog,
            forceUpdate: forceUpdate,
          );
          if (shouldUpdate == true && mounted) {
            setState(() => _statusText = 'Yuklanmoqda...');
            await _downloadAndInstall(downloadUrl);
            return;
          }
          if (forceUpdate) return; // Majburiy yangilash — ilovaga kirmaslik
        }
      }
    } catch (e) {
      // Yangilash tekshirib bo'lmadi — davom etamiz
      debugPrint('Yangilash tekshirish xatosi: $e');
      if (mounted) setState(() => _statusText = '');
    }

    if (!mounted) return;
    setState(() => _statusText = 'Ma\'lumotlar tayyorlanmoqda...');
    // Offline tizimni ishga tushirish
    await SyncService().init();
    if (!mounted) return;
    setState(() => _statusText = '');

    // Rozilik ekrani — birinchi ochilishda
    final hasConsent = await session.hasConsent();
    final isLoggedIn = await session.isLoggedIn();
    if (!mounted) return;

    if (!hasConsent) {
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => ConsentScreen(
            nextScreenBuilder: (_) => isLoggedIn ? const DashboardScreen() : const LoginScreen(),
          ),
        ),
      );
      return;
    }

    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => isLoggedIn ? const DashboardScreen() : const LoginScreen(),
      ),
    );
  }

  Future<bool?> _showUpdateDialog({
    required String serverVersion,
    required String changelog,
    required bool forceUpdate,
  }) {
    return showDialog<bool>(
      context: context,
      barrierDismissible: !forceUpdate,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.system_update, color: Color(0xFF017449)),
            SizedBox(width: 8),
            Text('Yangilanish'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Yangi versiya: $serverVersion', style: const TextStyle(fontWeight: FontWeight.bold)),
            Text('Joriy versiya: $appVersion', style: TextStyle(color: Colors.grey[600], fontSize: 13)),
            if (changelog.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(changelog, style: const TextStyle(fontSize: 13)),
            ],
          ],
        ),
        actions: [
          if (!forceUpdate)
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Keyinroq'),
            ),
          ElevatedButton.icon(
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.download, size: 18),
            label: const Text('Yangilash'),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449), foregroundColor: Colors.white),
          ),
        ],
      ),
    );
  }

  Future<void> _downloadAndInstall(String downloadPath) async {
    try {
      final fullUrl = '${ApiService.baseUrl}$downloadPath';
      setState(() => _statusText = 'APK yuklanmoqda...');

      // APK ni yuklab olish
      final request = await HttpClient().getUrl(Uri.parse(fullUrl));
      final response = await request.close();
      final bytes = await response.fold<List<int>>([], (prev, chunk) {
        prev.addAll(chunk);
        if (mounted) {
          final mb = prev.length / 1024 / 1024;
          setState(() => _statusText = 'Yuklanmoqda... ${mb.toStringAsFixed(1)} MB');
        }
        return prev;
      });

      // Faylga saqlash — cache papkasiga (FileProvider taniydi)
      final cacheDir = Directory('${Directory.systemTemp.path}/totli_apk');
      if (!await cacheDir.exists()) await cacheDir.create(recursive: true);
      final file = File('${cacheDir.path}/totli-agent.apk');
      await file.writeAsBytes(bytes);

      if (!mounted) return;
      setState(() => _statusText = 'O\'rnatish...');

      // Android Intent orqali APK o'rnatish
      const platform = MethodChannel('app.totli/installer');
      try {
        await platform.invokeMethod('installApk', {'path': file.path});
        // Intent yuborildi — o'rnatish dialogi ko'rinishi kerak
        // Foydalanuvchi o'rnatgandan keyin ilova qayta ochiladi
      } catch (e) {
        debugPrint('APK install xatosi: $e');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('O\'rnatish xatosi: $e\nFayl: ${file.path}'),
              duration: const Duration(seconds: 8),
              backgroundColor: Colors.red,
            ),
          );
          await Future.delayed(const Duration(seconds: 3));
          _continueToApp();
        }
      }
    } catch (e) {
      debugPrint('APK yuklash xatosi: $e');
      if (mounted) {
        setState(() => _statusText = '');
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Yangilanish yuklab bo\'lmadi. Keyinroq qayta uriniladi.'),
            backgroundColor: Colors.orange,
            duration: Duration(seconds: 3),
          ),
        );
        await Future.delayed(const Duration(seconds: 1));
        _continueToApp();
      }
    }
  }

  void _continueToApp() async {
    final session = SessionService();
    final isLoggedIn = await session.isLoggedIn();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => isLoggedIn ? const DashboardScreen() : const LoginScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF017449), Color(0xFF015A38)],
          ),
        ),
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.store, size: 80, color: Colors.white.withOpacity(0.9)),
              const SizedBox(height: 24),
              Text(
                'TOTLI HOLVA',
                style: TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.bold,
                  color: Colors.white.withOpacity(0.95),
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'v$appVersion',
                style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.6)),
              ),
              const SizedBox(height: 48),
              const CircularProgressIndicator(color: Color(0xFFFFB50D)),
              if (_statusText.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(_statusText, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.7))),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
