import 'dart:async';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'api_service.dart';
import 'session_service.dart';
import 'offline_db_service.dart';

/// Internet holatini kuzatish va offline buyurtmalarni sinxronlash
class SyncService {
  static SyncService? _instance;
  SyncService._();
  factory SyncService() => _instance ??= SyncService._();

  final OfflineDbService _db = OfflineDbService();
  final SessionService _session = SessionService();
  final Connectivity _connectivity = Connectivity();

  StreamSubscription<ConnectivityResult>? _connectivitySub;
  bool _isOnline = true;
  bool _isSyncing = false;

  bool get isOnline => _isOnline;
  bool get isSyncing => _isSyncing;

  // Callback — UI yangilash uchun
  VoidCallback? onStatusChanged;

  /// Ilovani ishga tushirganda chaqirish
  Future<void> init() async {
    final result = await _connectivity.checkConnectivity();
    _isOnline = result != ConnectivityResult.none;

    _connectivitySub?.cancel();
    _connectivitySub = _connectivity.onConnectivityChanged.listen((result) {
      final wasOnline = _isOnline;
      _isOnline = result != ConnectivityResult.none;
      if (!wasOnline && _isOnline) {
        _onReconnected();
      }
      onStatusChanged?.call();
    });

    // Boshlang'ich cache
    if (_isOnline) {
      _cacheDataSilently();
    }
  }

  void dispose() {
    _connectivitySub?.cancel();
  }

  /// Internet qaytganda chaqiriladi
  void _onReconnected() {
    onStatusChanged?.call();
    // Auto sync qilinmaydi — foydalanuvchi o'zi bosadi
  }

  /// Partners va products ni serverdan yuklab cache qilish
  Future<bool> refreshCache() async {
    final token = await _session.getToken();
    if (token == null) return false;

    try {
      final results = await Future.wait([
        ApiService.getPartners(token),
        ApiService.getProducts(token),
      ]).timeout(const Duration(seconds: 10));

      if (results[0]['success'] == true) {
        final partners = List<Map<String, dynamic>>.from(results[0]['partners'] ?? []);
        await _db.cachePartners(partners);
      }
      if (results[1]['success'] == true) {
        final products = List<Map<String, dynamic>>.from(results[1]['products'] ?? []);
        await _db.cacheProducts(products);
      }
      return true;
    } catch (e) {
      debugPrint('Cache yangilash xatosi: $e');
      return false;
    }
  }

  /// Fon rejimda cache yangilash (xatolik ko'rsatilmaydi)
  Future<void> _cacheDataSilently() async {
    try {
      await refreshCache();
    } catch (_) {}
  }

  /// Pending buyurtmalarni serverga yuborish
  /// Natija: {synced: int, failed: int, errors: List<String>}
  Future<Map<String, dynamic>> syncPendingOrders() async {
    if (_isSyncing) return {'synced': 0, 'failed': 0, 'errors': ['Allaqachon sinxronlanmoqda']};
    if (!_isOnline) return {'synced': 0, 'failed': 0, 'errors': ['Internet yo\'q']};

    _isSyncing = true;
    onStatusChanged?.call();

    final token = await _session.getToken();
    if (token == null) {
      _isSyncing = false;
      onStatusChanged?.call();
      return {'synced': 0, 'failed': 0, 'errors': ['Token yo\'q']};
    }

    final pending = await _db.getPendingOrders();
    int synced = 0;
    int failed = 0;
    final errors = <String>[];

    for (final order in pending) {
      final localId = order['local_id'] as int;
      final partnerName = (order['partner_name'] ?? 'Noma\'lum mijoz').toString();
      try {
        // Items validatsiyasi
        final rawItems = order['items'];
        if (rawItems == null || rawItems is! List || rawItems.isEmpty) {
          await _db.markOrderFailed(localId, 'Mahsulotlar topilmadi');
          failed++;
          errors.add('$partnerName: Mahsulotlar topilmadi');
          continue;
        }

        final items = rawItems.map((i) {
          final m = i is Map ? i : <String, dynamic>{};
          return {
            'product_id': m['product_id'],
            'qty': m['qty'],
          };
        }).toList();

        final result = await ApiService.createOrder(token, {
          'partner_id': order['partner_id'],
          'payment_type': order['payment_type'] ?? 'naqd',
          'items': items,
        });

        if (result['success'] == true) {
          await _db.markOrderSynced(
            localId,
            serverId: result['id'] as int?,
            serverNumber: result['order_number']?.toString(),
          );
          synced++;
        } else {
          final err = (result['error']?.toString()) ?? 'Noma\'lum xato';
          await _db.markOrderFailed(localId, err);
          failed++;
          errors.add('$partnerName: $err');
        }
      } catch (e) {
        await _db.markOrderFailed(localId, e.toString());
        failed++;
        errors.add('$partnerName: $e');
      }
    }

    _isSyncing = false;
    onStatusChanged?.call();

    // Muvaffaqiyatli sync dan keyin cache yangilash
    if (synced > 0) {
      _cacheDataSilently();
    }

    return {'synced': synced, 'failed': failed, 'errors': errors};
  }

  /// Pending vizitlarni serverga yuborish
  Future<Map<String, dynamic>> syncPendingVisits() async {
    if (!_isOnline) return {'synced': 0, 'failed': 0};
    final token = await _session.getToken();
    if (token == null) return {'synced': 0, 'failed': 0};

    final pending = await _db.getPendingVisits();
    int synced = 0;
    int failed = 0;

    for (final visit in pending) {
      final localId = visit['local_id'] as int;
      try {
        final result = await ApiService.checkIn(token,
          partnerId: visit['partner_id'] as int,
          latitude: (visit['latitude'] as num).toDouble(),
          longitude: (visit['longitude'] as num).toDouble(),
          notes: visit['notes'] as String?,
        );
        if (result['success'] == true) {
          final serverId = result['visit_id'] as int?;
          // Agar check_out bo'lgan bo'lsa — checkout ham yuboramiz
          if (visit['check_out_time'] != null && serverId != null) {
            await ApiService.checkOut(token, visitId: serverId, notes: visit['notes'] as String?);
          }
          await _db.markVisitSynced(localId, serverId: serverId);
          synced++;
        } else {
          await _db.markVisitFailed(localId, (result['error']?.toString()) ?? 'Xato');
          failed++;
        }
      } catch (e) {
        await _db.markVisitFailed(localId, e.toString());
        failed++;
      }
    }
    return {'synced': synced, 'failed': failed};
  }

  /// Pending yetkazish statuslarini serverga yuborish
  Future<Map<String, dynamic>> syncPendingDeliveries() async {
    if (!_isOnline) return {'synced': 0, 'failed': 0};
    final token = await _session.getToken();
    if (token == null) return {'synced': 0, 'failed': 0};

    final pending = await _db.getPendingDeliveryActions();
    int synced = 0;
    int failed = 0;
    final errors = <String>[];

    for (final action in pending) {
      final localId = action['local_id'] as int;
      final partnerName = (action['partner_name'] ?? '').toString();
      try {
        final result = await ApiService.updateDeliveryStatus(
          token,
          action['delivery_id'] as int,
          action['new_status'] as String,
          latitude: action['latitude'] != null ? (action['latitude'] as num).toDouble() : null,
          longitude: action['longitude'] != null ? (action['longitude'] as num).toDouble() : null,
          notes: action['notes'] as String?,
        );
        if (result['success'] == true) {
          await _db.markDeliveryActionSynced(localId);
          synced++;
        } else {
          final err = (result['error']?.toString()) ?? 'Xato';
          await _db.markDeliveryActionFailed(localId, err);
          failed++;
          errors.add('$partnerName: $err');
        }
      } catch (e) {
        await _db.markDeliveryActionFailed(localId, e.toString());
        failed++;
        errors.add('$partnerName: $e');
      }
    }

    // Muvaffaqiyatli sync dan keyin deliveries cache yangilash
    if (synced > 0) {
      try {
        final deliveriesResult = await ApiService.getDeliveries(token);
        if (deliveriesResult['success'] == true) {
          final deliveries = List<Map<String, dynamic>>.from(deliveriesResult['deliveries'] ?? []);
          await _db.cacheDeliveries(deliveries);
        }
      } catch (_) {}
    }

    return {'synced': synced, 'failed': failed, 'errors': errors};
  }

  /// Internet borligini tekshirish (real serverga ping)
  Future<bool> checkConnection() async {
    try {
      final result = await _connectivity.checkConnectivity();
      _isOnline = result != ConnectivityResult.none;
      if (_isOnline) {
        // Serverga haqiqiy ulanishni tekshirish
        final versionCheck = await ApiService.checkAppVersion();
        _isOnline = versionCheck.isNotEmpty;
      }
    } catch (_) {
      _isOnline = false;
    }
    onStatusChanged?.call();
    return _isOnline;
  }
}
