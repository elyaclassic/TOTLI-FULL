import 'dart:async';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../services/offline_db_service.dart';
import '../services/sync_service.dart';
import '../services/location_service.dart';

class VisitsScreen extends StatefulWidget {
  const VisitsScreen({super.key});

  @override
  State<VisitsScreen> createState() => _VisitsScreenState();
}

class _VisitsScreenState extends State<VisitsScreen> {
  final SessionService _session = SessionService();
  List<Map<String, dynamic>> _visits = [];
  List<Map<String, dynamic>> _partners = [];
  bool _isLoading = true;

  // Haftaning kunlari (dart: 1=Dush, 7=Yak; DB: 1=Dush, 6=Shanba, 0=Yak)
  static const _dayNames = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'];

  int get _todayVisitDay {
    // DateTime.now().weekday: 1=Mon..7=Sun
    // DB: 1=Dush, 2=Sesh, ..., 6=Shanba, 0=Yak
    final wd = DateTime.now().weekday; // 1-7
    return wd == 7 ? 0 : wd;
  }

  String get _todayName => _dayNames[_todayVisitDay];

  /// Bugungi kun bo'yicha rejadagi mijozlar
  List<Map<String, dynamic>> get _todayPlannedPartners {
    final today = _todayVisitDay;
    // Bugun vizit qilingan partner IDlari
    final visitedIds = <int>{};
    final todayStr = DateTime.now().toIso8601String().substring(0, 10);
    for (final v in _visits) {
      final vDate = (v['visit_date'] ?? v['check_in_time'] ?? '').toString();
      if (vDate.startsWith(todayStr)) {
        visitedIds.add(v['partner_id'] as int);
      }
    }
    return _partners.where((p) {
      final vd = p['visit_day'];
      return vd != null && vd == today && !visitedIds.contains(p['id']);
    }).toList();
  }

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) {
      if (mounted) setState(() => _isLoading = false);
      return;
    }

    final syncService = SyncService();
    final offlineDb = OfflineDbService();

    if (syncService.isOnline) {
      try {
        // Parallel yuklash + 10s umumiy timeout
        final results = await Future.wait([
          ApiService.getVisits(token),
          ApiService.getPartners(token),
        ]).timeout(const Duration(seconds: 10));
        final vResult = results[0];
        final pResult = results[1];
        if (mounted) {
          setState(() {
            _isLoading = false;
            if (vResult['success'] == true) _visits = List<Map<String, dynamic>>.from(vResult['visits'] ?? []);
            if (pResult['success'] == true) {
              _partners = List<Map<String, dynamic>>.from(pResult['partners'] ?? []);
              offlineDb.cachePartners(_partners);
            }
          });
        }
        // Online bo'lganda — offline vizitlarni sinxronlash
        syncService.syncPendingVisits();
      } catch (_) {
        // API xato yoki timeout — offline rejimga o'tish
        await _loadOfflineData(offlineDb);
      }
    } else {
      await _loadOfflineData(offlineDb);
    }
  }

  Future<void> _loadOfflineData(OfflineDbService offlineDb) async {
    _partners = await offlineDb.getCachedPartners();
    final offlineVisits = await offlineDb.getOfflineVisitsToday();
    _visits = offlineVisits.map((v) => {
      'partner_id': v['partner_id'],
      'partner_name': v['partner_name'],
      'check_in_time': v['check_in_time'],
      'check_out_time': v['check_out_time'],
      'visit_date': v['check_in_time'],
      'local_id': v['local_id'],
      'is_offline': true,
    }).toList();
    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _startVisitWithPartner(Map<String, dynamic> partner) async {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('GPS aniqlanmoqda...'), duration: Duration(seconds: 5)));
    try {
      final pos = await LocationService().getPosition();
      final token = await _session.getToken();
      if (token == null) return;

      final syncService = SyncService();
      if (syncService.isOnline) {
        try {
          // Online — serverga yuborish
          final result = await ApiService.checkIn(token, partnerId: partner['id'], latitude: pos.latitude, longitude: pos.longitude);
          if (!mounted) return;
          if (result['success'] == true) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${partner['name']} ga kirish belgilandi'), backgroundColor: Colors.green));
            _openActiveVisit({
              'id': result['visit_id'],
              'partner_id': partner['id'],
              'partner_name': partner['name'],
              'check_in_time': DateTime.now().toIso8601String(),
              'check_out_time': null,
              'status': 'visited',
            });
            return;
          } else {
            final err = result['error']?.toString() ?? '';
            if (err.contains('Timeout') || err.contains('Ulanish')) {
              // Server javob bermadi — offline saqlash
            } else {
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err.isNotEmpty ? err : 'Xato'), backgroundColor: Colors.red));
              return;
            }
          }
        } catch (_) {
          // API xato — offline ga tushish
        }
      }
      // Offline — local saqlash
      final offlineDb = OfflineDbService();
      final localId = await offlineDb.saveOfflineVisit(
        partnerId: partner['id'] as int,
        partnerName: (partner['name'] ?? '').toString(),
        latitude: pos.latitude,
        longitude: pos.longitude,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('${partner['name']} — offline vizit saqlandi'),
        backgroundColor: Colors.orange,
      ));
      _openActiveVisit({
        'local_id': localId,
        'partner_id': partner['id'],
        'partner_name': partner['name'],
        'check_in_time': DateTime.now().toIso8601String(),
        'check_out_time': null,
        'status': 'visited',
        'is_offline': true,
      });
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('GPS xato: $e'), backgroundColor: Colors.red));
    }
  }

  Future<void> _startVisit() async {
    if (_partners.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Avval mijozlar yuklansin')));
      return;
    }
    final partner = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => _PartnerPicker(partners: _partners),
    );
    if (partner == null || !mounted) return;
    _startVisitWithPartner(partner);
  }

  void _openActiveVisit(Map<String, dynamic> visit) async {
    final token = await _session.getToken();
    if (token == null || !mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _ActiveVisitPage(
          visit: visit,
          token: token,
          partners: _partners,
        ),
      ),
    );
    _loadData();
  }

  @override
  Widget build(BuildContext context) {
    final planned = _todayPlannedPartners;
    // Bugungi vizitlar
    final todayStr = DateTime.now().toIso8601String().substring(0, 10);
    final todayVisits = _visits.where((v) {
      final vDate = (v['visit_date'] ?? v['check_in_time'] ?? '').toString();
      return vDate.startsWith(todayStr);
    }).toList();
    return Scaffold(
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadData,
              child: ListView(
                children: [
                  // Bugungi reja
                  if (planned.isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Row(
                        children: [
                          const Icon(Icons.today, size: 18, color: Color(0xFF017449)),
                          const SizedBox(width: 6),
                          Text(
                            'Bugungi reja ($_todayName) — ${planned.length} ta mijoz',
                            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Color(0xFF017449)),
                          ),
                        ],
                      ),
                    ),
                    ...planned.map((p) => Card(
                      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      color: Colors.orange.shade50,
                      child: ListTile(
                        dense: true,
                        leading: CircleAvatar(
                          radius: 18,
                          backgroundColor: Colors.orange.shade100,
                          child: const Icon(Icons.store, color: Colors.orange, size: 18),
                        ),
                        title: Text(p['name'] ?? '', style: const TextStyle(fontWeight: FontWeight.w500, fontSize: 14)),
                        subtitle: Text(p['address'] ?? p['phone'] ?? '', style: const TextStyle(fontSize: 11)),
                        trailing: TextButton.icon(
                          onPressed: () => _startVisitWithPartner(p),
                          icon: const Icon(Icons.pin_drop, size: 16),
                          label: const Text('Kirish', style: TextStyle(fontSize: 12)),
                          style: TextButton.styleFrom(
                            foregroundColor: const Color(0xFF017449),
                            padding: const EdgeInsets.symmetric(horizontal: 8),
                          ),
                        ),
                      ),
                    )),
                    const Divider(height: 20, indent: 16, endIndent: 16),
                  ],
                  if (planned.isEmpty && todayVisits.isEmpty)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text(
                        'Bugun ($_todayName) rejadagi mijozlar yo\'q',
                        style: TextStyle(fontSize: 13, color: Colors.grey[600]),
                      ),
                    ),
                  // Bugungi vizitlar (mijoz bo'yicha guruhlangan)
                  if (todayVisits.isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                      child: Text(
                        'Bugungi vizitlar — ${todayVisits.length} ta',
                        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                      ),
                    ),
                    ..._groupByPartner(todayVisits).entries.map((e) => _buildGroupedVisitTile(e.key, e.value)),
                  ],
                  // Oldingi vizitlar (mijoz bo'yicha guruhlangan)
                  if (_visits.where((v) {
                    final vDate = (v['visit_date'] ?? v['check_in_time'] ?? '').toString();
                    return !vDate.startsWith(todayStr);
                  }).isNotEmpty) ...[
                    const Padding(
                      padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text('Oldingi vizitlar', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: Colors.grey)),
                    ),
                    ..._groupByPartner(_visits.where((v) {
                      final vDate = (v['visit_date'] ?? v['check_in_time'] ?? '').toString();
                      return !vDate.startsWith(todayStr);
                    }).toList()).entries.map((e) => _buildGroupedVisitTile(e.key, e.value)),
                  ],
                  const SizedBox(height: 80),
                ],
              ),
            ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _startVisit,
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
        icon: const Icon(Icons.pin_drop),
        label: const Text('Vizit boshlash'),
      ),
    );
  }

  /// Vizitlarni partner_id bo'yicha guruhlash (tartib saqlanadi)
  Map<String, List<Map<String, dynamic>>> _groupByPartner(List<Map<String, dynamic>> visits) {
    final map = <String, List<Map<String, dynamic>>>{};
    for (final v in visits) {
      final key = '${v['partner_id'] ?? 0}';
      map.putIfAbsent(key, () => []).add(v);
    }
    return map;
  }

  Widget _buildGroupedVisitTile(String partnerId, List<Map<String, dynamic>> visits) {
    final first = visits.first;
    final name = first['partner_name'] ?? 'Mijoz #$partnerId';
    final hasActive = visits.any((v) => v['check_out_time'] == null);
    final activeVisit = hasActive ? visits.firstWhere((v) => v['check_out_time'] == null) : null;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      color: hasActive ? Colors.green.shade50 : null,
      elevation: hasActive ? 3 : 1,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: hasActive ? () => _openActiveVisit(activeVisit!) : null,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: hasActive ? const Color(0xFF017449) : Colors.grey.shade200,
                child: Icon(Icons.pin_drop, color: hasActive ? Colors.white : Colors.grey, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    const SizedBox(height: 2),
                    ...visits.map((v) {
                      final checkIn = _formatTime(v['check_in_time']);
                      final checkOut = _formatTime(v['check_out_time']);
                      final isActive = v['check_out_time'] == null;
                      return Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(
                          'Kirish: $checkIn${checkOut.isNotEmpty ? '  →  Chiqish: $checkOut' : ''}${isActive ? '  (Faol)' : ''}',
                          style: TextStyle(fontSize: 11, color: isActive ? const Color(0xFF017449) : Colors.grey[600]),
                        ),
                      );
                    }),
                  ],
                ),
              ),
              if (hasActive)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: const Color(0xFF017449),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Text('Faol', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w500)),
                )
              else
                Column(
                  children: [
                    Text('Tugallangan', style: TextStyle(fontSize: 11, color: Colors.grey[500])),
                    if (visits.length > 1)
                      Text('${visits.length} vizit', style: TextStyle(fontSize: 10, color: Colors.grey[400])),
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildVisitTile(Map<String, dynamic> v) {
    final isActive = v['check_out_time'] == null;
    final checkIn = _formatTime(v['check_in_time']);
    final checkOut = _formatTime(v['check_out_time']);
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      color: isActive ? Colors.green.shade50 : null,
      elevation: isActive ? 3 : 1,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: isActive ? () => _openActiveVisit(v) : null,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: isActive ? const Color(0xFF017449) : Colors.grey.shade200,
                child: Icon(Icons.pin_drop, color: isActive ? Colors.white : Colors.grey, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      v['partner_name'] ?? 'Mijoz #${v['partner_id']}',
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Kirish: $checkIn',
                      style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                    ),
                    if (checkOut.isNotEmpty)
                      Text(
                        'Chiqish: $checkOut',
                        style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                      ),
                  ],
                ),
              ),
              if (isActive)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: const Color(0xFF017449),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Text('Faol', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w500)),
                )
              else
                Text('Tugallangan', style: TextStyle(fontSize: 11, color: Colors.grey[500])),
            ],
          ),
        ),
      ),
    );
  }

  String _formatTime(dynamic t) {
    if (t == null) return '';
    try {
      final dt = DateTime.parse(t.toString());
      return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return t.toString();
    }
  }
}


// ======================== AKTIV VIZIT SAHIFASI ========================

class _ActiveVisitPage extends StatefulWidget {
  final Map<String, dynamic> visit;
  final String token;
  final List<Map<String, dynamic>> partners;
  const _ActiveVisitPage({required this.visit, required this.token, required this.partners});

  @override
  State<_ActiveVisitPage> createState() => _ActiveVisitPageState();
}

class _ActiveVisitPageState extends State<_ActiveVisitPage> {
  final SessionService _session = SessionService();
  Map<String, dynamic>? _partnerDetail;
  List<Map<String, dynamic>> _debts = [];
  double _totalDebt = 0;
  bool _isLoading = true;
  bool _isEnding = false;

  int get _partnerId => widget.visit['partner_id'] as int;
  String get _partnerName => widget.visit['partner_name'] ?? 'Mijoz';

  @override
  void initState() {
    super.initState();
    _loadPartnerInfo();
  }

  bool get _isOfflineVisit => widget.visit['is_offline'] == true;

  Future<void> _loadPartnerInfo() async {
    final syncService = SyncService();
    if (!syncService.isOnline) {
      // Offline — faqat asosiy ma'lumotlarni ko'rsatish
      if (mounted) setState(() => _isLoading = false);
      return;
    }
    setState(() => _isLoading = true);
    final detailFuture = ApiService.getPartnerDetail(widget.token, _partnerId);
    final debtsFuture = ApiService.getPartnerDebts(widget.token, _partnerId);
    final results = await Future.wait([detailFuture, debtsFuture]);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (results[0]['success'] == true) {
          _partnerDetail = results[0]['partner'] as Map<String, dynamic>?;
        }
        if (results[1]['success'] == true) {
          _debts = List<Map<String, dynamic>>.from(results[1]['debts'] ?? []);
          _totalDebt = (results[1]['total_debt'] ?? 0).toDouble();
        }
      });
    }
  }

  Future<void> _endVisit() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Vizitni yakunlash'),
        content: Text('$_partnerName ga vizitni yakunlaysizmi?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Bekor')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
            child: const Text('Yakunlash'),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    setState(() => _isEnding = true);

    if (_isOfflineVisit) {
      // Offline vizitni yakunlash
      final offlineDb = OfflineDbService();
      await offlineDb.checkOutOfflineVisit(widget.visit['local_id'] as int);
      if (!mounted) return;
      setState(() => _isEnding = false);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit yakunlandi (offline)'), backgroundColor: Colors.orange));
      Navigator.pop(context);
    } else {
      // Online vizitni yakunlash
      try {
        final result = await ApiService.checkOut(widget.token, visitId: widget.visit['id']).timeout(const Duration(seconds: 10));
        if (!mounted) return;
        setState(() => _isEnding = false);
        if (result['success'] == true) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit yakunlandi'), backgroundColor: Colors.green));
          Navigator.pop(context);
        } else {
          final err = result['error']?.toString() ?? '';
          if (err.contains('Timeout') || err.contains('Ulanish')) {
            // Server javob bermadi — vizitni lokal yakunlash
            setState(() => _isEnding = false);
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit yakunlandi (offline). Internet qaytganda sinxronlanadi.'), backgroundColor: Colors.orange));
            Navigator.pop(context);
          } else {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err.isNotEmpty ? err : 'Xato'), backgroundColor: Colors.red));
          }
        }
      } catch (_) {
        // Timeout/xato — vizitni baribir yakunlash
        if (!mounted) return;
        setState(() => _isEnding = false);
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit yakunlandi (offline). Internet qaytganda sinxronlanadi.'), backgroundColor: Colors.orange));
        Navigator.pop(context);
      }
    }
  }

  void _openCreateOrder() async {
    // Loading ko'rsatish
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulotlar yuklanmoqda...'), duration: Duration(seconds: 2)));

    List<Map<String, dynamic>> products;
    final offlineDb = OfflineDbService();

    // Avval cache dan o'qish (darhol)
    products = await offlineDb.getCachedProducts();

    // Cache bo'sh va online bo'lsa — serverdan yuklash
    if (products.isEmpty && SyncService().isOnline) {
      try {
        final productsResult = await ApiService.getProducts(widget.token).timeout(const Duration(seconds: 5));
        products = List<Map<String, dynamic>>.from(productsResult['products'] ?? []);
        if (products.isNotEmpty) offlineDb.cacheProducts(products);
      } catch (_) {}
    }

    // Online bo'lsa va cache eski bo'lsa — yangilash (lekin cache bor, shuning uchun kutmaymiz)
    if (products.isNotEmpty && SyncService().isOnline) {
      // Fon da yangilash
      ApiService.getProducts(widget.token).timeout(const Duration(seconds: 5)).then((r) {
        final p = List<Map<String, dynamic>>.from(r['products'] ?? []);
        if (p.isNotEmpty) offlineDb.cacheProducts(p);
      }).catchError((_) {});
    }

    if (!mounted) return;
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    if (products.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Mahsulotlar topilmadi. Avval internetga ulanib ilovani oching — keyin offline ham ishlaydi.'),
        duration: Duration(seconds: 4),
      ));
      return;
    }
    final result = await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _VisitOrderPage(
          partnerId: _partnerId,
          partnerName: _partnerName,
          products: products,
          token: widget.token,
          discount: (_partnerDetail?['discount_percent'] ?? 0).toDouble(),
        ),
      ),
    );
    if (result == true) _loadPartnerInfo();
  }

  void _openReturn() async {
    final ordersResult = await ApiService.getPartnerCompletedOrders(widget.token, _partnerId);
    if (!mounted) return;
    final orders = List<Map<String, dynamic>>.from(ordersResult['orders'] ?? []);
    if (orders.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Qaytarish uchun buyurtma yo\'q')));
      return;
    }
    final result = await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _VisitReturnPage(
          partnerId: _partnerId,
          partnerName: _partnerName,
          orders: orders,
          token: widget.token,
        ),
      ),
    );
    if (result == true) _loadPartnerInfo();
  }

  void _openExchange() async {
    // Obmen = Vozvrat + Yangi buyurtma. Avval vozvrat.
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Obmen: avval qaytarish, keyin yangi buyurtma bering')),
    );
    _openReturn();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_partnerName, style: const TextStyle(fontSize: 16)),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Mijoz ma'lumotlari
                  _buildPartnerCard(),
                  const SizedBox(height: 12),
                  // Qarzdorlik
                  _buildDebtCard(),
                  const SizedBox(height: 16),
                  // Amallar
                  _buildActionButtons(),
                  const SizedBox(height: 16),
                  // Qarz tafsilotlari
                  if (_debts.isNotEmpty) _buildDebtDetails(),
                  const SizedBox(height: 24),
                  // Yakunlash
                  SizedBox(
                    height: 48,
                    child: OutlinedButton.icon(
                      onPressed: _isEnding ? null : _endVisit,
                      icon: _isEnding
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.logout, color: Colors.red),
                      label: Text(_isEnding ? 'Yakunlanmoqda...' : 'Vizitni yakunlash'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.red,
                        side: const BorderSide(color: Colors.red),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _buildPartnerCard() {
    final p = _partnerDetail;
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.store, color: Color(0xFF017449), size: 28),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(_partnerName, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
                ),
              ],
            ),
            if (p != null) ...[
              const Divider(height: 16),
              if ((p['phone'] ?? '').isNotEmpty)
                _infoRow(Icons.phone, p['phone']),
              if ((p['address'] ?? '').isNotEmpty)
                _infoRow(Icons.location_on, p['address']),
              if ((p['category'] ?? '').isNotEmpty)
                _infoRow(Icons.category, 'Kategoriya: ${p['category']}'),
              if ((p['discount_percent'] ?? 0) > 0)
                _infoRow(Icons.discount, 'Chegirma: ${p['discount_percent']}%'),
            ],
            const Divider(height: 16),
            Row(
              children: [
                if (p != null && p['lat'] != null && p['lng'] != null)
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () async {
                        final lat = p['lat'].toString();
                        final lng = p['lng'].toString();
                        final geoUri = Uri.parse('geo:$lat,$lng?q=$lat,$lng');
                        final webUri = Uri.parse('https://www.google.com/maps/search/?api=1&query=$lat,$lng');

                        if (await launchUrl(geoUri, mode: LaunchMode.externalNonBrowserApplication)) {
                          return;
                        }
                        if (await launchUrl(webUri, mode: LaunchMode.externalApplication)) {
                          return;
                        }
                        if (!mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Xarita ilovasini ochib bo\'lmadi'),
                            backgroundColor: Colors.red,
                          ),
                        );
                      },
                      icon: const Icon(Icons.map, size: 16),
                      label: const Text('Xaritada', style: TextStyle(fontSize: 11)),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFF017449),
                        side: const BorderSide(color: Color(0xFF017449)),
                        padding: const EdgeInsets.symmetric(vertical: 8),
                      ),
                    ),
                  ),
                if (p != null && p['lat'] != null && p['lng'] != null)
                  const SizedBox(width: 8),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => _setPartnerLocation(p ?? {'id': _partnerId}),
                    icon: const Icon(Icons.my_location, size: 16),
                    label: Text(
                      (p != null && p['lat'] != null) ? 'Lokatsiya yangilash' : 'Lokatsiya o\'rnatish',
                      style: const TextStyle(fontSize: 11),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF017449),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 8),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _setPartnerLocation(Map<String, dynamic> partner) async {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('GPS aniqlanmoqda...'), duration: Duration(seconds: 5)));
    try {
      final pos = await LocationService().getPosition();
      final syncService = SyncService();
      if (syncService.isOnline) {
        try {
          final token = widget.token;
          final result = await ApiService.setPartnerLocation(token, partner['id'], pos.latitude, pos.longitude).timeout(const Duration(seconds: 10));
          if (!mounted) return;
          if (result['success'] == true) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Lokatsiya saqlandi!'), backgroundColor: Colors.green));
            setState(() {
              partner['lat'] = pos.latitude;
              partner['lng'] = pos.longitude;
            });
            return;
          }
        } catch (_) {
          // Server javob bermadi — lokal saqlash
        }
      }
      // Offline yoki server xato — lokal saqlash
      if (!mounted) return;
      setState(() {
        partner['lat'] = pos.latitude;
        partner['lng'] = pos.longitude;
      });
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Lokatsiya saqlandi (offline). Internet qaytganda sinxronlanadi.'),
        backgroundColor: Colors.orange,
      ));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('GPS xatosi: $e'), backgroundColor: Colors.red));
    }
  }

  Widget _infoRow(IconData icon, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          Icon(icon, size: 16, color: Colors.grey),
          const SizedBox(width: 8),
          Flexible(child: Text(text, style: const TextStyle(fontSize: 13))),
        ],
      ),
    );
  }

  Widget _buildDebtCard() {
    final balance = _partnerDetail?['balance'] ?? _totalDebt;
    final balanceVal = (balance is num) ? balance.toDouble() : 0.0;
    final hasDebt = balanceVal > 0;
    return Card(
      color: hasDebt ? Colors.red.shade50 : Colors.green.shade50,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            Icon(
              hasDebt ? Icons.warning_amber_rounded : Icons.check_circle_outline,
              color: hasDebt ? Colors.red : Colors.green,
              size: 32,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    hasDebt ? 'Qarzdorlik' : 'Qarz yo\'q',
                    style: TextStyle(
                      fontSize: 13,
                      color: hasDebt ? Colors.red[700] : Colors.green[700],
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  Text(
                    '${_formatMoney(balanceVal)} so\'m',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: hasDebt ? Colors.red[800] : Colors.green[800],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildActionButtons() {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _actionButton(
                icon: Icons.shopping_cart,
                label: 'Buyurtma\nberish',
                color: const Color(0xFF017449),
                onTap: _openCreateOrder,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _actionButton(
                icon: Icons.swap_horiz,
                label: 'Obmen\n(almashtirish)',
                color: Colors.orange.shade700,
                onTap: _openExchange,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _actionButton(
                icon: Icons.assignment_return,
                label: 'Vozvrat\n(qaytarish)',
                color: Colors.red.shade600,
                onTap: _openReturn,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _actionButton({required IconData icon, required String label, required Color color, required VoidCallback onTap}) {
    return Material(
      color: color.withOpacity(0.1),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Column(
            children: [
              Icon(icon, color: color, size: 32),
              const SizedBox(height: 6),
              Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDebtDetails() {
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Qarz tafsilotlari', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ..._debts.map((d) => Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(d['number'] ?? '', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
                        Text(d['date'] ?? '', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                      ],
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(_formatMoney((d['debt'] ?? 0).toDouble()), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.red)),
                      Text('/ ${_formatMoney((d['total'] ?? 0).toDouble())}', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                    ],
                  ),
                ],
              ),
            )),
          ],
        ),
      ),
    );
  }

  String _formatMoney(double v) {
    final s = v.toStringAsFixed(0);
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0 && s[i] != '-') buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }
}


// ======================== VIZIT ICHIDA BUYURTMA ========================

class _VisitOrderPage extends StatefulWidget {
  final int partnerId;
  final String partnerName;
  final List<Map<String, dynamic>> products;
  final String token;
  final double discount;
  const _VisitOrderPage({required this.partnerId, required this.partnerName, required this.products, required this.token, required this.discount});

  @override
  State<_VisitOrderPage> createState() => _VisitOrderPageState();
}

class _VisitOrderPageState extends State<_VisitOrderPage> {
  String _paymentType = 'naqd';
  final Map<int, double> _cart = {};
  bool _isSending = false;
  String _searchQuery = '';

  List<Map<String, dynamic>> get _filteredProducts {
    if (_searchQuery.isEmpty) return widget.products;
    final q = _searchQuery.toLowerCase();
    return widget.products.where((p) => (p['name'] ?? '').toString().toLowerCase().contains(q)).toList();
  }

  double get _subtotal {
    double t = 0;
    _cart.forEach((pid, qty) {
      final p = widget.products.firstWhere((x) => x['id'] == pid, orElse: () => {});
      t += (p['price'] ?? 0).toDouble() * qty;
    });
    return t;
  }

  double get _total => _subtotal * (1 - widget.discount / 100);

  Future<void> _editQty(int pid, String productName, double currentQty) async {
    final controller = TextEditingController(text: currentQty > 0 ? currentQty.toStringAsFixed(currentQty == currentQty.roundToDouble() ? 0 : 1) : '');
    final result = await showDialog<double>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(productName, style: const TextStyle(fontSize: 15)),
        content: TextField(
          controller: controller,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Miqdor', border: OutlineInputBorder()),
          onSubmitted: (v) => Navigator.pop(ctx, double.tryParse(v) ?? 0),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, 0.0), child: const Text('O\'chirish')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, double.tryParse(controller.text) ?? 0),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449)),
            child: const Text('OK', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
    if (result == null) return;
    setState(() {
      if (result <= 0) {
        _cart.remove(pid);
      } else {
        _cart[pid] = result;
      }
    });
  }

  Future<void> _submit() async {
    if (_cart.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulot qo\'shing')));
      return;
    }
    setState(() => _isSending = true);
    final items = _cart.entries.map((e) => {'product_id': e.key, 'qty': e.value}).toList();
    final syncService = SyncService();

    if (syncService.isOnline) {
      try {
        final result = await ApiService.createOrder(widget.token, {
          'partner_id': widget.partnerId,
          'payment_type': _paymentType,
          'items': items,
        }).timeout(const Duration(seconds: 10));
        if (!mounted) return;
        setState(() => _isSending = false);
        if (result['success'] == true) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Buyurtma: ${result['order_number'] ?? ''}'),
            backgroundColor: Colors.green,
          ));
          Navigator.pop(context, true);
          return;
        }
        // Server xato — offline ga tushish
      } catch (_) {
        // Timeout — offline saqlash
      }
    }

    // Offline — lokal bazaga saqlash
    final offlineDb = OfflineDbService();
    final itemsWithDetails = _cart.entries.map((e) {
      final product = widget.products.firstWhere((p) => p['id'] == e.key, orElse: () => {});
      return {'product_id': e.key, 'qty': e.value, 'name': product['name'] ?? '', 'price': product['price'] ?? 0};
    }).toList();
    double total = 0;
    for (final i in itemsWithDetails) { total += (i['qty'] as num) * ((i['price'] as num?)?.toDouble() ?? 0); }

    await offlineDb.saveOfflineOrder(
      partnerId: widget.partnerId,
      partnerName: widget.partnerName,
      paymentType: _paymentType,
      items: itemsWithDetails,
      total: total,
    );
    if (!mounted) return;
    setState(() => _isSending = false);
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('Buyurtma offline saqlandi. Internet qaytganda sinxronlanadi.'),
      backgroundColor: Colors.orange,
    ));
    Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Buyurtma: ${widget.partnerName}', style: const TextStyle(fontSize: 15)),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              children: [
                Row(
                  children: [
                    const Text('To\'lov: ', style: TextStyle(fontWeight: FontWeight.w500)),
                    ChoiceChip(label: const Text('Naqd'), selected: _paymentType == 'naqd', onSelected: (_) => setState(() => _paymentType = 'naqd')),
                    const SizedBox(width: 8),
                    ChoiceChip(label: const Text('Qarz'), selected: _paymentType == 'qarz', onSelected: (_) => setState(() => _paymentType = 'qarz')),
                  ],
                ),
                const SizedBox(height: 8),
                TextField(
                  decoration: InputDecoration(
                    hintText: 'Mahsulot qidirish...',
                    prefixIcon: const Icon(Icons.search),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                  ),
                  onChanged: (v) => setState(() => _searchQuery = v),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: _filteredProducts.length,
              itemBuilder: (ctx, i) {
                final p = _filteredProducts[i];
                final pid = p['id'] as int;
                final qty = _cart[pid] ?? 0;
                final stock = (p['stock'] ?? 0).toDouble();
                return ListTile(
                  dense: true,
                  title: Text(p['name'] ?? '', style: const TextStyle(fontSize: 14)),
                  subtitle: Text(
                    '${_formatPrice(p['price'])} | Qoldiq: ${stock.toStringAsFixed(0)} ${p['unit'] ?? ''}',
                    style: TextStyle(fontSize: 11, color: stock > 0 ? Colors.grey : Colors.red),
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (qty > 0) IconButton(
                        icon: const Icon(Icons.remove_circle_outline, size: 22),
                        onPressed: () => setState(() { if (qty <= 1) {
                          _cart.remove(pid);
                        } else {
                          _cart[pid] = qty - 1;
                        } }),
                      ),
                      if (qty > 0) GestureDetector(
                        onTap: () => _editQty(pid, p['name'] ?? '', qty),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                            border: Border.all(color: const Color(0xFF017449)),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            qty == qty.roundToDouble() ? qty.toStringAsFixed(0) : qty.toStringAsFixed(1),
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF017449)),
                          ),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.add_circle, color: Color(0xFF017449), size: 22),
                        onPressed: () => setState(() => _cart[pid] = qty + 1),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          if (_cart.isNotEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 8, offset: const Offset(0, -2))],
              ),
              child: Row(
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${_cart.length} ta mahsulot', style: const TextStyle(fontSize: 12, color: Colors.grey)),
                      if (widget.discount > 0)
                        Text('Chegirma: ${widget.discount.toStringAsFixed(0)}%', style: const TextStyle(fontSize: 11, color: Colors.green)),
                      Text('${_formatPrice(_total)} so\'m', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const Spacer(),
                  ElevatedButton(
                    onPressed: _isSending ? null : _submit,
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449), foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12)),
                    child: _isSending ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Yuborish'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  String _formatPrice(dynamic v) {
    final d = (v is num) ? v.toDouble() : 0.0;
    final s = d.toStringAsFixed(0);
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }
}


// ======================== VIZIT ICHIDA VOZVRAT ========================

class _VisitReturnPage extends StatefulWidget {
  final int partnerId;
  final String partnerName;
  final List<Map<String, dynamic>> orders;
  final String token;
  const _VisitReturnPage({required this.partnerId, required this.partnerName, required this.orders, required this.token});

  @override
  State<_VisitReturnPage> createState() => _VisitReturnPageState();
}

class _VisitReturnPageState extends State<_VisitReturnPage> {
  int? _selectedOrderId;
  Map<String, dynamic>? _selectedOrder;
  final Map<int, double> _returnQty = {};
  bool _isSending = false;

  void _selectOrder(Map<String, dynamic> order) {
    setState(() {
      _selectedOrderId = order['id'] as int;
      _selectedOrder = order;
      _returnQty.clear();
    });
  }

  double get _returnTotal {
    if (_selectedOrder == null) return 0;
    final items = List<Map<String, dynamic>>.from(_selectedOrder!['items'] ?? []);
    double t = 0;
    _returnQty.forEach((pid, qty) {
      if (qty <= 0) return;
      final item = items.firstWhere((x) => x['product_id'] == pid, orElse: () => {});
      t += (item['price'] ?? 0).toDouble() * qty;
    });
    return t;
  }

  Future<void> _submit() async {
    final items = <Map<String, dynamic>>[];
    _returnQty.forEach((pid, qty) {
      if (qty > 0) items.add({'product_id': pid, 'qty': qty});
    });
    if (items.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Qaytarish miqdorini kiriting')));
      return;
    }
    setState(() => _isSending = true);
    final result = await ApiService.createReturn(widget.token, {
      'order_id': _selectedOrderId,
      'items': items,
    });
    if (!mounted) return;
    setState(() => _isSending = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Vozvrat: ${result['return_number'] ?? ''}'),
        backgroundColor: Colors.green,
      ));
      Navigator.pop(context, true);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Vozvrat: ${widget.partnerName}', style: const TextStyle(fontSize: 15)),
        backgroundColor: Colors.red.shade600,
        foregroundColor: Colors.white,
      ),
      body: _selectedOrder == null ? _buildOrderList() : _buildReturnItems(),
    );
  }

  Widget _buildOrderList() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('Qaysi buyurtmadan qaytarish?', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: widget.orders.length,
            itemBuilder: (ctx, i) {
              final o = widget.orders[i];
              return Card(
                margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: ListTile(
                  leading: const CircleAvatar(
                    backgroundColor: Color(0xFFE3F2FD),
                    child: Icon(Icons.receipt, color: Colors.blue, size: 20),
                  ),
                  title: Text(o['number'] ?? '#${o['id']}', style: const TextStyle(fontWeight: FontWeight.w500)),
                  subtitle: Text('${o['date']} | ${_formatPrice(o['total'])} so\'m', style: const TextStyle(fontSize: 12)),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _selectOrder(o),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildReturnItems() {
    final items = List<Map<String, dynamic>>.from(_selectedOrder!['items'] ?? []);
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          color: Colors.grey.shade100,
          child: Row(
            children: [
              IconButton(icon: const Icon(Icons.arrow_back), onPressed: () => setState(() { _selectedOrder = null; _selectedOrderId = null; _returnQty.clear(); })),
              Expanded(child: Text('${_selectedOrder!['number']} | ${_selectedOrder!['date']}', style: const TextStyle(fontWeight: FontWeight.w500))),
            ],
          ),
        ),
        const Padding(
          padding: EdgeInsets.all(12),
          child: Text('Qaytarish miqdorini kiriting:', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: items.length,
            itemBuilder: (ctx, i) {
              final item = items[i];
              final pid = item['product_id'] as int;
              final maxQty = (item['quantity'] ?? 0).toDouble();
              final retQty = _returnQty[pid] ?? 0;
              return ListTile(
                title: Text(item['name'] ?? '', style: const TextStyle(fontSize: 14)),
                subtitle: Text(
                  'Sotilgan: ${maxQty.toStringAsFixed(0)} | Narx: ${_formatPrice(item['price'])}',
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (retQty > 0) IconButton(
                      icon: const Icon(Icons.remove_circle_outline, size: 22, color: Colors.red),
                      onPressed: () => setState(() {
                        if (retQty <= 1) {
                          _returnQty.remove(pid);
                        } else {
                          _returnQty[pid] = retQty - 1;
                        }
                      }),
                    ),
                    if (retQty > 0) Text(retQty.toStringAsFixed(0), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.red)),
                    IconButton(
                      icon: const Icon(Icons.add_circle, size: 22, color: Colors.red),
                      onPressed: retQty >= maxQty ? null : () => setState(() => _returnQty[pid] = retQty + 1),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
        if (_returnQty.values.any((q) => q > 0))
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 8, offset: const Offset(0, -2))],
            ),
            child: Row(
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Qaytarish summasi:', style: TextStyle(fontSize: 12, color: Colors.grey)),
                    Text('${_formatPrice(_returnTotal)} so\'m', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.red)),
                  ],
                ),
                const Spacer(),
                ElevatedButton(
                  onPressed: _isSending ? null : _submit,
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12)),
                  child: _isSending
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Qaytarish'),
                ),
              ],
            ),
          ),
      ],
    );
  }

  String _formatPrice(dynamic v) {
    final d = (v is num) ? v.toDouble() : 0.0;
    final s = d.toStringAsFixed(0);
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }
}


// ======================== MIJOZ TANLASH ========================

class _PartnerPicker extends StatefulWidget {
  final List<Map<String, dynamic>> partners;
  const _PartnerPicker({required this.partners});

  @override
  State<_PartnerPicker> createState() => _PartnerPickerState();
}

class _PartnerPickerState extends State<_PartnerPicker> {
  String _search = '';

  List<Map<String, dynamic>> get _filtered {
    if (_search.isEmpty) return widget.partners;
    final q = _search.toLowerCase();
    return widget.partners.where((p) => (p['name'] ?? '').toString().toLowerCase().contains(q)).toList();
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.7,
      minChildSize: 0.4,
      maxChildSize: 0.9,
      expand: false,
      builder: (ctx, scroll) => Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2))),
                const SizedBox(height: 12),
                const Text('Mijozni tanlang', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                TextField(
                  decoration: InputDecoration(hintText: 'Qidirish...', prefixIcon: const Icon(Icons.search), border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)), isDense: true),
                  onChanged: (v) => setState(() => _search = v),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              controller: scroll,
              itemCount: _filtered.length,
              itemBuilder: (ctx, i) {
                final p = _filtered[i];
                final balance = (p['balance'] ?? 0).toDouble();
                final hasDebt = balance > 0;
                return ListTile(
                  leading: Icon(Icons.store, color: hasDebt ? Colors.red : const Color(0xFF017449)),
                  title: Text(p['name'] ?? ''),
                  subtitle: Text(
                    '${p['address'] ?? p['phone'] ?? ''}${hasDebt ? ' | Qarz: ${_formatMoney(balance)}' : ''}',
                    style: TextStyle(fontSize: 12, color: hasDebt ? Colors.red : null),
                  ),
                  onTap: () => Navigator.pop(ctx, p),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  String _formatMoney(double v) {
    final s = v.toStringAsFixed(0);
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0 && s[i] != '-') buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }
}
