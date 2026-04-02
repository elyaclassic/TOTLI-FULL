import 'dart:async';
import 'package:geolocator/geolocator.dart';
import 'package:battery_plus/battery_plus.dart';
import 'api_service.dart';
import 'session_service.dart';

class LocationService {
  // Singleton
  static final LocationService _instance = LocationService._internal();
  factory LocationService() => _instance;
  LocationService._internal();

  Timer? _timer;
  final SessionService _session = SessionService();
  final Battery _battery = Battery();
  bool isTracking = false;
  String? lastError;
  DateTime? lastSentAt;

  /// Ruxsat tekshirish va so'rash
  Future<bool> checkPermission() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return false;

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    return permission == LocationPermission.whileInUse ||
        permission == LocationPermission.always;
  }

  /// Lokatsiya yuborish
  Future<bool> sendLocation() async {
    // Server URL tiklanganligini tekshirish
    final savedUrl = await _session.getApiUrl();
    if (savedUrl != null && savedUrl.isNotEmpty) {
      ApiService.setBaseUrl(savedUrl);
    }

    final token = await _session.getToken();
    final role = await _session.getRole();
    if (token == null || token.isEmpty) {
      lastError = 'Token yo\'q';
      return false;
    }
    if (role != 'agent' && role != 'driver') {
      lastError = 'Rol noto\'g\'ri: $role';
      return false;
    }

    final hasPermission = await checkPermission();
    if (!hasPermission) {
      lastError = 'GPS ruxsat berilmagan';
      return false;
    }

    try {
      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 15),
      );

      int batteryLevel = 100;
      try {
        batteryLevel = await _battery.batteryLevel;
      } catch (_) {}

      final result = await ApiService.sendLocation(
        userType: role ?? 'agent',
        token: token,
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy: position.accuracy,
        battery: batteryLevel,
      );

      if (result['success'] == true) {
        lastError = null;
        lastSentAt = DateTime.now();
        return true;
      } else {
        lastError = result['error']?.toString() ?? 'Server xatosi';
        return false;
      }
    } catch (e) {
      // Timeout xatolarini qisqartirish (foydalanuvchini chalkashtirilmasin)
      final msg = e.toString();
      if (msg.contains('TimeoutException') || msg.contains('Ulanish xatosi')) {
        lastError = 'Server javob bermadi';
      } else {
        lastError = msg;
      }
      return false;
    }
  }

  /// GPS koordinatalarini olish (offline ham ishlaydi)
  /// 1-qadam: Oxirgi ma'lum pozitsiya (darhol)
  /// 2-qadam: Yangi GPS so'rov (60s timeout, medium accuracy — sputnik + cell tower)
  /// 3-qadam: Agar ikkalasi ham bo'lmasa — xato
  Future<Position> getPosition() async {
    final hasPermission = await checkPermission();
    if (!hasPermission) {
      throw Exception('GPS ruxsat berilmagan');
    }

    // Avval oxirgi ma'lum pozitsiyani olish (darhol, kutmasdan)
    Position? lastKnown;
    try {
      lastKnown = await Geolocator.getLastKnownPosition();
    } catch (_) {}

    // Yangi GPS so'rov — avval medium (tezroq, cell tower ham ishlatadi)
    try {
      return await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.medium,
        timeLimit: const Duration(seconds: 15),
      );
    } catch (_) {}

    // Medium ishlamadi — high accuracy bilan urinish (sof GPS, ko'proq vaqt)
    try {
      return await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 45),
      );
    } catch (_) {}

    // Hech biri ishlamadi — oxirgi ma'lum pozitsiyani qaytarish
    if (lastKnown != null) {
      return lastKnown;
    }

    throw Exception('GPS aniqlab bo\'lmadi. Joylashuv xizmati yoqilganligini tekshiring.');
  }

  /// Har 2 daqiqada lokatsiya yuborishni boshlash
  void startPeriodicTracking() {
    if (isTracking) return; // allaqachon ishlayapti
    isTracking = true;
    sendLocation(); // Darhol birinchi yuborish
    _timer = Timer.periodic(const Duration(minutes: 2), (_) => sendLocation());
  }

  void stopPeriodicTracking() {
    _timer?.cancel();
    _timer = null;
    isTracking = false;
  }
}
