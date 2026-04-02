import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as p;

/// Offline ma'lumotlar bazasi — partners, products cache va offline buyurtmalar navbati
class OfflineDbService {
  static OfflineDbService? _instance;
  static Database? _db;

  OfflineDbService._();
  factory OfflineDbService() => _instance ??= OfflineDbService._();

  Future<Database> get database async {
    _db ??= await _initDb();
    return _db!;
  }

  Future<Database> _initDb() async {
    final dbPath = await getDatabasesPath();
    final path = p.join(dbPath, 'totli_offline.db');
    return openDatabase(
      path,
      version: 3,
      onCreate: (db, version) async {
        // Partners cache
        await db.execute('''
          CREATE TABLE partners (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            balance REAL DEFAULT 0,
            visit_day INTEGER,
            data TEXT,
            updated_at TEXT
          )
        ''');
        // Products cache
        await db.execute('''
          CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL DEFAULT 0,
            stock REAL DEFAULT 0,
            unit TEXT,
            data TEXT,
            updated_at TEXT
          )
        ''');
        // Offline buyurtmalar navbati
        await db.execute('''
          CREATE TABLE offline_orders (
            local_id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            partner_name TEXT,
            payment_type TEXT DEFAULT 'naqd',
            items TEXT NOT NULL,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            server_id INTEGER,
            server_number TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            synced_at TEXT
          )
        ''');
        // Deliveries cache
        await db.execute('''
          CREATE TABLE deliveries (
            id INTEGER PRIMARY KEY,
            partner_name TEXT,
            partner_address TEXT,
            partner_phone TEXT,
            partner_phone2 TEXT,
            order_number TEXT,
            status TEXT DEFAULT 'pending',
            total REAL DEFAULT 0,
            items TEXT,
            latitude REAL,
            longitude REAL,
            landmark TEXT,
            notes TEXT,
            data TEXT,
            updated_at TEXT
          )
        ''');
        // Offline delivery status o'zgarishlari navbati
        await db.execute('''
          CREATE TABLE offline_delivery_actions (
            local_id INTEGER PRIMARY KEY AUTOINCREMENT,
            delivery_id INTEGER NOT NULL,
            partner_name TEXT,
            new_status TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            notes TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at TEXT NOT NULL,
            synced_at TEXT
          )
        ''');
        // Sync metadata
        await db.execute('''
          CREATE TABLE sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
          )
        ''');
        // Offline vizitlar
        await db.execute('''
          CREATE TABLE offline_visits (
            local_id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            partner_name TEXT,
            latitude REAL,
            longitude REAL,
            check_in_time TEXT NOT NULL,
            check_out_time TEXT,
            notes TEXT,
            status TEXT DEFAULT 'pending',
            server_id INTEGER,
            error_message TEXT,
            synced_at TEXT
          )
        ''');
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS offline_visits (
              local_id INTEGER PRIMARY KEY AUTOINCREMENT,
              partner_id INTEGER NOT NULL,
              partner_name TEXT,
              latitude REAL,
              longitude REAL,
              check_in_time TEXT NOT NULL,
              check_out_time TEXT,
              notes TEXT,
              status TEXT DEFAULT 'pending',
              server_id INTEGER,
              error_message TEXT,
              synced_at TEXT
            )
          ''');
        }
        if (oldVersion < 3) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS deliveries (
              id INTEGER PRIMARY KEY,
              partner_name TEXT,
              partner_address TEXT,
              partner_phone TEXT,
              partner_phone2 TEXT,
              order_number TEXT,
              status TEXT DEFAULT 'pending',
              total REAL DEFAULT 0,
              items TEXT,
              latitude REAL,
              longitude REAL,
              landmark TEXT,
              notes TEXT,
              data TEXT,
              updated_at TEXT
            )
          ''');
          await db.execute('''
            CREATE TABLE IF NOT EXISTS offline_delivery_actions (
              local_id INTEGER PRIMARY KEY AUTOINCREMENT,
              delivery_id INTEGER NOT NULL,
              partner_name TEXT,
              new_status TEXT NOT NULL,
              latitude REAL,
              longitude REAL,
              notes TEXT,
              status TEXT DEFAULT 'pending',
              error_message TEXT,
              created_at TEXT NOT NULL,
              synced_at TEXT
            )
          ''');
        }
      },
    );
  }

  // ==================== PARTNERS ====================

  Future<void> cachePartners(List<Map<String, dynamic>> partners) async {
    final db = await database;
    final batch = db.batch();
    batch.delete('partners');
    final now = DateTime.now().toIso8601String();
    for (final p in partners) {
      batch.insert('partners', {
        'id': p['id'],
        'name': p['name'] ?? '',
        'phone': p['phone'] ?? '',
        'address': p['address'] ?? '',
        'balance': (p['balance'] ?? 0).toDouble(),
        'visit_day': p['visit_day'],
        'data': jsonEncode(p),
        'updated_at': now,
      });
    }
    await batch.commit(noResult: true);
    await _setMeta('partners_cached_at', now);
  }

  Future<List<Map<String, dynamic>>> getCachedPartners({String? search}) async {
    final db = await database;
    List<Map<String, dynamic>> rows;
    if (search != null && search.isNotEmpty) {
      rows = await db.query('partners',
          where: 'name LIKE ?', whereArgs: ['%$search%'], orderBy: 'name');
    } else {
      rows = await db.query('partners', orderBy: 'name');
    }
    return rows.map((r) {
      if (r['data'] != null) {
        return Map<String, dynamic>.from(jsonDecode(r['data'] as String));
      }
      return Map<String, dynamic>.from(r);
    }).toList();
  }

  // ==================== PRODUCTS ====================

  Future<void> cacheProducts(List<Map<String, dynamic>> products) async {
    final db = await database;
    final batch = db.batch();
    batch.delete('products');
    final now = DateTime.now().toIso8601String();
    for (final p in products) {
      batch.insert('products', {
        'id': p['id'],
        'name': p['name'] ?? '',
        'price': (p['price'] ?? 0).toDouble(),
        'stock': (p['stock'] ?? 0).toDouble(),
        'unit': p['unit'] ?? '',
        'data': jsonEncode(p),
        'updated_at': now,
      });
    }
    await batch.commit(noResult: true);
    await _setMeta('products_cached_at', now);
  }

  Future<List<Map<String, dynamic>>> getCachedProducts() async {
    final db = await database;
    final rows = await db.query('products', orderBy: 'name');
    return rows.map((r) {
      if (r['data'] != null) {
        return Map<String, dynamic>.from(jsonDecode(r['data'] as String));
      }
      return Map<String, dynamic>.from(r);
    }).toList();
  }

  // ==================== OFFLINE ORDERS ====================

  /// Offline buyurtma saqlash.
  /// Bir mijozga bir kunda bitta buyurtma — agar bugungi pending buyurtma bor bo'lsa, itemlar birlashtiriladi.
  Future<int> saveOfflineOrder({
    required int partnerId,
    required String partnerName,
    required String paymentType,
    required List<Map<String, dynamic>> items,
    required double total,
  }) async {
    final db = await database;
    final today = DateTime.now().toIso8601String().substring(0, 10);

    // Shu mijozning bugungi pending buyurtmasi bormi?
    final existing = await db.query('offline_orders',
        where: "partner_id = ? AND status = 'pending' AND created_at LIKE ?",
        whereArgs: [partnerId, '$today%']);

    if (existing.isNotEmpty) {
      // Mavjud buyurtmaga itemlarni qo'shish
      final row = existing.first;
      final localId = row['local_id'] as int;
      final existingItems = row['items'] is String
          ? List<Map<String, dynamic>>.from(jsonDecode(row['items'] as String))
          : <Map<String, dynamic>>[];

      // Itemlarni birlashtirish — bir xil product_id bo'lsa qty qo'shiladi
      for (final newItem in items) {
        final pid = newItem['product_id'];
        final idx = existingItems.indexWhere((e) => e['product_id'] == pid);
        if (idx >= 0) {
          // Mavjud mahsulot — qty qo'shish
          existingItems[idx] = Map<String, dynamic>.from(existingItems[idx]);
          existingItems[idx]['qty'] = ((existingItems[idx]['qty'] ?? 0) as num).toDouble()
              + ((newItem['qty'] ?? 0) as num).toDouble();
          // total yangilash
          final price = ((existingItems[idx]['price'] ?? 0) as num).toDouble();
          existingItems[idx]['total'] = existingItems[idx]['qty'] * price;
        } else {
          // Yangi mahsulot
          existingItems.add(Map<String, dynamic>.from(newItem));
        }
      }

      // Umumiy summani qayta hisoblash
      double newTotal = 0;
      for (final i in existingItems) {
        final qty = ((i['qty'] ?? 0) as num).toDouble();
        final price = ((i['price'] ?? 0) as num).toDouble();
        newTotal += qty * price;
      }

      await db.update('offline_orders', {
        'items': jsonEncode(existingItems),
        'total': newTotal,
      }, where: 'local_id = ?', whereArgs: [localId]);

      return localId;
    }

    // Yangi buyurtma yaratish
    return db.insert('offline_orders', {
      'partner_id': partnerId,
      'partner_name': partnerName,
      'payment_type': paymentType,
      'items': jsonEncode(items),
      'total': total,
      'status': 'pending',
      'created_at': DateTime.now().toIso8601String(),
    });
  }

  Future<List<Map<String, dynamic>>> getPendingOrders() async {
    final db = await database;
    final rows = await db.query('offline_orders',
        where: 'status = ?', whereArgs: ['pending'], orderBy: 'created_at DESC');
    return rows.map((r) {
      final m = Map<String, dynamic>.from(r);
      if (m['items'] is String) {
        m['items'] = jsonDecode(m['items'] as String);
      }
      return m;
    }).toList();
  }

  Future<List<Map<String, dynamic>>> getAllOfflineOrders() async {
    final db = await database;
    final rows = await db.query('offline_orders', orderBy: 'created_at DESC');
    return rows.map((r) {
      final m = Map<String, dynamic>.from(r);
      if (m['items'] is String) {
        m['items'] = jsonDecode(m['items'] as String);
      }
      return m;
    }).toList();
  }

  Future<void> markOrderSynced(int localId, {int? serverId, String? serverNumber}) async {
    final db = await database;
    await db.update('offline_orders', {
      'status': 'synced',
      'server_id': serverId,
      'server_number': serverNumber,
      'synced_at': DateTime.now().toIso8601String(),
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<void> markOrderFailed(int localId, String error) async {
    final db = await database;
    await db.update('offline_orders', {
      'status': 'failed',
      'error_message': error,
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<void> resetFailedOrder(int localId) async {
    final db = await database;
    await db.update('offline_orders', {
      'status': 'pending',
      'error_message': null,
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<void> deleteOfflineOrder(int localId) async {
    final db = await database;
    await db.delete('offline_orders', where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<int> getPendingOrderCount() async {
    final db = await database;
    final result = await db.rawQuery("SELECT COUNT(*) as cnt FROM offline_orders WHERE status = 'pending'");
    return (result.first['cnt'] as int?) ?? 0;
  }

  // ==================== SYNC META ====================

  Future<void> _setMeta(String key, String value) async {
    final db = await database;
    await db.insert('sync_meta', {
      'key': key,
      'value': value,
      'updated_at': DateTime.now().toIso8601String(),
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<String?> getMeta(String key) async {
    final db = await database;
    final rows = await db.query('sync_meta', where: 'key = ?', whereArgs: [key]);
    if (rows.isEmpty) return null;
    return rows.first['value'] as String?;
  }

  Future<bool> hasCachedData() async {
    final p = await getMeta('partners_cached_at');
    final pr = await getMeta('products_cached_at');
    return p != null && pr != null;
  }

  // ==================== OFFLINE VISITS ====================

  Future<int> saveOfflineVisit({
    required int partnerId,
    required String partnerName,
    required double latitude,
    required double longitude,
    String? notes,
  }) async {
    final db = await database;
    return db.insert('offline_visits', {
      'partner_id': partnerId,
      'partner_name': partnerName,
      'latitude': latitude,
      'longitude': longitude,
      'check_in_time': DateTime.now().toIso8601String(),
      'status': 'pending',
    });
  }

  Future<void> checkOutOfflineVisit(int localId, {String? notes}) async {
    final db = await database;
    await db.update('offline_visits', {
      'check_out_time': DateTime.now().toIso8601String(),
      'notes': notes,
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<List<Map<String, dynamic>>> getPendingVisits() async {
    final db = await database;
    return db.query('offline_visits',
        where: 'status = ?', whereArgs: ['pending'], orderBy: 'check_in_time DESC');
  }

  Future<List<Map<String, dynamic>>> getOfflineVisitsToday() async {
    final db = await database;
    final today = DateTime.now().toIso8601String().substring(0, 10);
    return db.query('offline_visits',
        where: 'check_in_time LIKE ?', whereArgs: ['$today%'], orderBy: 'check_in_time DESC');
  }

  Future<void> markVisitSynced(int localId, {int? serverId}) async {
    final db = await database;
    await db.update('offline_visits', {
      'status': 'synced',
      'server_id': serverId,
      'synced_at': DateTime.now().toIso8601String(),
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<void> markVisitFailed(int localId, String error) async {
    final db = await database;
    await db.update('offline_visits', {
      'status': 'failed',
      'error_message': error,
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  // ==================== DELIVERIES CACHE ====================

  Future<void> cacheDeliveries(List<Map<String, dynamic>> deliveries) async {
    final db = await database;
    final batch = db.batch();
    batch.delete('deliveries');
    final now = DateTime.now().toIso8601String();
    for (final d in deliveries) {
      batch.insert('deliveries', {
        'id': d['id'],
        'partner_name': d['partner_name'] ?? '',
        'partner_address': d['partner_address'] ?? d['delivery_address'] ?? '',
        'partner_phone': d['partner_phone'] ?? '',
        'partner_phone2': d['partner_phone2'] ?? '',
        'order_number': d['order_number'] ?? d['number'] ?? '',
        'status': d['status'] ?? 'pending',
        'total': (d['total'] ?? 0).toDouble(),
        'items': jsonEncode(d['items'] ?? []),
        'latitude': d['latitude'],
        'longitude': d['longitude'],
        'landmark': d['landmark'] ?? '',
        'notes': d['notes'] ?? '',
        'data': jsonEncode(d),
        'updated_at': now,
      });
    }
    await batch.commit(noResult: true);
    await _setMeta('deliveries_cached_at', now);
  }

  Future<List<Map<String, dynamic>>> getCachedDeliveries() async {
    final db = await database;
    final rows = await db.query('deliveries', orderBy: 'id DESC');
    return rows.map((r) {
      if (r['data'] != null) {
        return Map<String, dynamic>.from(jsonDecode(r['data'] as String));
      }
      return Map<String, dynamic>.from(r);
    }).toList();
  }

  /// Lokal cache da yetkazish statusini yangilash (UI uchun)
  Future<void> updateCachedDeliveryStatus(int deliveryId, String newStatus) async {
    final db = await database;
    // data JSON ni ham yangilash
    final rows = await db.query('deliveries', where: 'id = ?', whereArgs: [deliveryId]);
    if (rows.isNotEmpty && rows.first['data'] != null) {
      final data = Map<String, dynamic>.from(jsonDecode(rows.first['data'] as String));
      data['status'] = newStatus;
      await db.update('deliveries', {
        'status': newStatus,
        'data': jsonEncode(data),
      }, where: 'id = ?', whereArgs: [deliveryId]);
    } else {
      await db.update('deliveries', {
        'status': newStatus,
      }, where: 'id = ?', whereArgs: [deliveryId]);
    }
  }

  // ==================== OFFLINE DELIVERY ACTIONS ====================

  Future<int> saveOfflineDeliveryAction({
    required int deliveryId,
    required String partnerName,
    required String newStatus,
    double? latitude,
    double? longitude,
    String? notes,
  }) async {
    final db = await database;
    return db.insert('offline_delivery_actions', {
      'delivery_id': deliveryId,
      'partner_name': partnerName,
      'new_status': newStatus,
      'latitude': latitude,
      'longitude': longitude,
      'notes': notes,
      'status': 'pending',
      'created_at': DateTime.now().toIso8601String(),
    });
  }

  Future<List<Map<String, dynamic>>> getPendingDeliveryActions() async {
    final db = await database;
    return db.query('offline_delivery_actions',
        where: 'status = ?', whereArgs: ['pending'], orderBy: 'created_at ASC');
  }

  Future<void> markDeliveryActionSynced(int localId) async {
    final db = await database;
    await db.update('offline_delivery_actions', {
      'status': 'synced',
      'synced_at': DateTime.now().toIso8601String(),
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<void> markDeliveryActionFailed(int localId, String error) async {
    final db = await database;
    await db.update('offline_delivery_actions', {
      'status': 'failed',
      'error_message': error,
    }, where: 'local_id = ?', whereArgs: [localId]);
  }

  Future<int> getPendingDeliveryActionCount() async {
    final db = await database;
    final result = await db.rawQuery("SELECT COUNT(*) as cnt FROM offline_delivery_actions WHERE status = 'pending'");
    return (result.first['cnt'] as int?) ?? 0;
  }
}
