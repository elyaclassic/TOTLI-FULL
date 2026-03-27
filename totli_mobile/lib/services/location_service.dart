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
      lastError = e.toString();
      return false;
    }
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
