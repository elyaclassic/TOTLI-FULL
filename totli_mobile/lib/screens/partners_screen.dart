import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../services/offline_db_service.dart';
import '../services/sync_service.dart';
import 'visit_photo_screen.dart';
import 'call_log_dialog.dart';
import 'sms_compose_screen.dart';

class PartnersScreen extends StatefulWidget {
  const PartnersScreen({super.key});

  @override
  State<PartnersScreen> createState() => _PartnersScreenState();
}

class _PartnersScreenState extends State<PartnersScreen> {
  final SessionService _session = SessionService();
  List<Map<String, dynamic>> _partners = [];
  List<Map<String, dynamic>> _visits = [];
  bool _isLoading = true;

  static const _dayNames = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'];

  int get _todayVisitDay {
    final wd = DateTime.now().weekday; // 1=Mon..7=Sun
    return wd == 7 ? 0 : wd; // DB: 0=Yak, 1=Dush, ..., 6=Shanba
  }

  /// Bugun vizit qilingan partner IDlari
  Set<int> get _todayVisitedIds {
    final todayStr = DateTime.now().toIso8601String().substring(0, 10);
    final ids = <int>{};
    for (final v in _visits) {
      final vDate = (v['visit_date'] ?? v['check_in_time'] ?? '').toString();
      if (vDate.startsWith(todayStr)) {
        ids.add(v['partner_id'] as int);
      }
    }
    return ids;
  }

  /// Bugungi rejadagi mijozlar
  List<Map<String, dynamic>> get _todayPartners {
    final today = _todayVisitDay;
    return _partners.where((p) => p['visit_day'] == today).toList();
  }

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;

    final syncService = SyncService();
    final offlineDb = OfflineDbService();

    if (syncService.isOnline) {
      final pResult = await ApiService.getPartners(token);
      final vResult = await ApiService.getVisits(token);
      if (mounted) {
        setState(() {
          _isLoading = false;
          if (pResult['success'] == true) {
            _partners = List<Map<String, dynamic>>.from(pResult['partners'] ?? []);
            // Cache yangilash
            offlineDb.cachePartners(_partners);
          }
          if (vResult['success'] == true) {
            _visits = List<Map<String, dynamic>>.from(vResult['visits'] ?? []);
          }
        });
      }
    } else {
      // Offline — cache dan o'qish
      _partners = await offlineDb.getCachedPartners();
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final todayPartners = _todayPartners;
    final visitedIds = _todayVisitedIds;
    // Kirish kerak (hali kirmagan)
    final pending = todayPartners.where((p) => !visitedIds.contains(p['id'])).toList();
    // Kirgan
    final visited = todayPartners.where((p) => visitedIds.contains(p['id'])).toList();

    return Scaffold(
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadData,
              child: ListView(
                children: [
                  // Sarlavha
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                    child: Row(
                      children: [
                        const Icon(Icons.today, size: 20, color: Color(0xFF017449)),
                        const SizedBox(width: 8),
                        Text(
                          '${_dayNames[_todayVisitDay]} — ${todayPartners.length} ta mijoz',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Color(0xFF017449)),
                        ),
                      ],
                    ),
                  ),

                  if (todayPartners.isEmpty)
                    Padding(
                      padding: const EdgeInsets.all(32),
                      child: Center(
                        child: Column(
                          children: [
                            Icon(Icons.event_busy, size: 48, color: Colors.grey[400]),
                            const SizedBox(height: 12),
                            Text('Bugun rejadagi mijozlar yo\'q', style: TextStyle(color: Colors.grey[600])),
                          ],
                        ),
                      ),
                    ),

                  // Kirish kerak bo'lganlar
                  if (pending.isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                      child: Text(
                        'Kirish kerak — ${pending.length} ta',
                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Colors.orange[800]),
                      ),
                    ),
                    ...pending.map((p) => _buildPartnerCard(p, visited: false)),
                  ],

                  // Kirilganlar
                  if (visited.isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text(
                        'Kirilgan — ${visited.length} ta',
                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Colors.green[700]),
                      ),
                    ),
                    ...visited.map((p) => _buildPartnerCard(p, visited: true)),
                  ],

                  const SizedBox(height: 80),
                ],
              ),
            ),
    );
  }

  Widget _buildPartnerCard(Map<String, dynamic> p, {required bool visited}) {
    final balance = (p['balance'] ?? 0).toDouble();
    final hasDebt = balance < 0;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      color: visited ? Colors.green.shade50 : null,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _openPartnerActions(p),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Row(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor: visited ? Colors.green.shade100 : Colors.orange.shade100,
                child: Icon(
                  visited ? Icons.check : Icons.store,
                  color: visited ? Colors.green : Colors.orange,
                  size: 20,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      p['name'] ?? '',
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                    ),
                    if ((p['phone'] ?? '').isNotEmpty || (p['address'] ?? '').isNotEmpty)
                      Text(
                        p['phone'] ?? p['address'] ?? '',
                        style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                      ),
                  ],
                ),
              ),
              if (balance != 0)
                Text(
                  '${balance > 0 ? "+" : ""}${_formatBalance(balance)}',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: hasDebt ? Colors.red : Colors.green,
                  ),
                ),
              const SizedBox(width: 4),
              const Icon(Icons.chevron_right, size: 20, color: Colors.grey),
            ],
          ),
        ),
      ),
    );
  }

  void _openPartnerActions(Map<String, dynamic> p) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2))),
              const SizedBox(height: 16),
              Text(p['name'] ?? '', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              if ((p['phone'] ?? '').isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(p['phone'], style: TextStyle(color: Colors.grey[600])),
              ],
              const SizedBox(height: 20),
              // Buyurtmalarni ko'rish
              _actionTile(
                icon: Icons.receipt_long,
                label: 'Buyurtmalarni ko\'rish',
                color: Colors.blue,
                onTap: () {
                  Navigator.pop(ctx);
                  _openPartnerOrders(p);
                },
              ),
              const SizedBox(height: 8),
              // Vizit boshlash
              if (!_todayVisitedIds.contains(p['id']))
                _actionTile(
                  icon: Icons.pin_drop,
                  label: 'Vizit boshlash',
                  color: const Color(0xFF017449),
                  onTap: () {
                    Navigator.pop(ctx);
                    _startVisit(p);
                  },
                ),
              // Yo'nalish (agar lat/lng bor bo'lsa)
              if (p['lat'] != null && p['lng'] != null) ...[
                const SizedBox(height: 8),
                _actionTile(
                  icon: Icons.navigation,
                  label: 'Yo\'nalish ochish',
                  color: Colors.orange,
                  onTap: () {
                    Navigator.pop(ctx);
                    _openNavSheet(
                      (p['lat'] as num).toDouble(),
                      (p['lng'] as num).toDouble(),
                      p['name'] ?? '',
                    );
                  },
                ),
              ],
              // Qo'ng'iroq
              if ((p['phone'] ?? '').toString().isNotEmpty) ...[
                const SizedBox(height: 8),
                _actionTile(
                  icon: Icons.phone,
                  label: 'Qo\'ng\'iroq qilish',
                  color: Colors.green,
                  onTap: () {
                    Navigator.pop(ctx);
                    CallLogFlow.startCallAndLog(
                      context: context,
                      phone: (p['phone'] ?? '').toString(),
                      partnerName: p['name'] ?? '',
                      partnerId: p['id'] as int?,
                    );
                  },
                ),
                const SizedBox(height: 8),
                _actionTile(
                  icon: Icons.sms,
                  label: 'SMS yuborish',
                  color: Colors.teal,
                  onTap: () {
                    Navigator.pop(ctx);
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => SmsComposeScreen(
                          partnerId: p['id'] as int?,
                          partnerName: p['name'] ?? '',
                          phone: (p['phone'] ?? '').toString(),
                        ),
                      ),
                    );
                  },
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _openNavSheet(double lat, double lng, String name) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2))),
              const SizedBox(height: 12),
              Text('Yo\'nalish: $name', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold), textAlign: TextAlign.center),
              const SizedBox(height: 16),
              _navItem(ctx, 'Yandex Maps', Icons.map, Colors.red,
                  'https://yandex.com/maps/?rtext=~$lat,$lng&rtt=auto'),
              const SizedBox(height: 8),
              _navItem(ctx, 'Google Maps', Icons.navigation, Colors.blue,
                  'https://www.google.com/maps/dir/?api=1&destination=$lat,$lng&travelmode=driving'),
              const SizedBox(height: 8),
              _navItem(ctx, '2GIS', Icons.location_on, Colors.green,
                  'https://2gis.uz/geo/$lng,$lat'),
              const SizedBox(height: 12),
            ],
          ),
        ),
      ),
    );
  }

  Widget _navItem(BuildContext ctx, String label, IconData icon, Color color, String url) {
    return Material(
      color: color.withOpacity(0.08),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          Navigator.pop(ctx);
          await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Icon(icon, color: color, size: 24),
              const SizedBox(width: 14),
              Text(label, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: color)),
              const Spacer(),
              Icon(Icons.chevron_right, color: color, size: 20),
            ],
          ),
        ),
      ),
    );
  }

  Widget _actionTile({required IconData icon, required String label, required Color color, required VoidCallback onTap}) {
    return Material(
      color: color.withOpacity(0.08),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Icon(icon, color: color, size: 24),
              const SizedBox(width: 14),
              Text(label, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: color)),
              const Spacer(),
              Icon(Icons.chevron_right, color: color, size: 20),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _startVisit(Map<String, dynamic> partner) async {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('GPS aniqlanmoqda...')));
    try {
      final pos = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high, timeLimit: const Duration(seconds: 10));
      final token = await _session.getToken();
      if (token == null) return;
      final result = await ApiService.checkIn(token, partnerId: partner['id'], latitude: pos.latitude, longitude: pos.longitude);
      if (!mounted) return;
      if (result['success'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${partner['name']} ga kirish belgilandi'), backgroundColor: Colors.green));
        _loadData();
        // Vizit rasm ekranini ochish
        final visitId = result['visit_id'];
        if (visitId is int) {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => VisitPhotoScreen(
                visitId: visitId,
                partnerName: partner['name'] ?? '',
              ),
            ),
          );
        }
      } else if (result['error_code'] == 'OPEN_VISIT') {
        _showOpenVisitDialog(result['open_visit'] ?? {});
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('GPS xato: $e'), backgroundColor: Colors.red));
    }
  }

  void _showOpenVisitDialog(Map<String, dynamic> openVisit) {
    final partnerName = (openVisit['partner_name'] ?? 'Mijoz').toString();
    final checkInRaw = (openVisit['check_in_time'] ?? '').toString();
    String checkInStr = '';
    if (checkInRaw.isNotEmpty) {
      try {
        final dt = DateTime.parse(checkInRaw).toLocal();
        checkInStr = '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
      } catch (_) {}
    }
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(children: [
          Icon(Icons.warning_amber, color: Colors.orange),
          SizedBox(width: 8),
          Text('Ochiq vizit bor', style: TextStyle(fontSize: 17)),
        ]),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Siz hali oldingi vizitni tugatmagansiz. Yangi tashrif boshlash uchun avval uni yakunlang.',
              style: TextStyle(fontSize: 14),
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: Colors.orange.shade50, borderRadius: BorderRadius.circular(8)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(partnerName, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                  if (checkInStr.isNotEmpty)
                    Text('Kirish vaqti: $checkInStr', style: TextStyle(fontSize: 12, color: Colors.grey[700])),
                ],
              ),
            ),
            const SizedBox(height: 10),
            const Text(
              'Vizitlar tabiga o\'tib, faol vizitni oching va "Chiqish" tugmasini bosing.',
              style: TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Yopish'),
          ),
        ],
      ),
    );
  }

  void _openPartnerOrders(Map<String, dynamic> partner) async {
    final token = await _session.getToken();
    if (token == null || !mounted) return;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _PartnerOrdersPage(
          partnerId: partner['id'] as int,
          partnerName: partner['name'] ?? '',
          token: token,
        ),
      ),
    ).then((_) => _loadData());
  }

  String _formatBalance(double v) {
    final neg = v < 0;
    final s = v.abs().toStringAsFixed(0);
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
      buf.write(s[i]);
    }
    return neg ? '-${buf.toString()}' : buf.toString();
  }
}


// ======================== MIJOZ BUYURTMALARI SAHIFASI ========================

class _PartnerOrdersPage extends StatefulWidget {
  final int partnerId;
  final String partnerName;
  final String token;
  const _PartnerOrdersPage({required this.partnerId, required this.partnerName, required this.token});

  @override
  State<_PartnerOrdersPage> createState() => _PartnerOrdersPageState();
}

class _PartnerOrdersPageState extends State<_PartnerOrdersPage> {
  List<Map<String, dynamic>> _orders = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadOrders();
  }

  Future<void> _loadOrders() async {
    setState(() => _isLoading = true);
    final result = await ApiService.getPartnerOrders(widget.token, widget.partnerId);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (result['success'] == true) {
          _orders = List<Map<String, dynamic>>.from(result['orders'] ?? []);
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.partnerName, style: const TextStyle(fontSize: 16)),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _orders.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.receipt_long, size: 48, color: Colors.grey[400]),
                      const SizedBox(height: 12),
                      const Text('Buyurtmalar yo\'q', style: TextStyle(color: Colors.grey)),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadOrders,
                  child: ListView.builder(
                    padding: const EdgeInsets.only(top: 8, bottom: 16),
                    itemCount: _orders.length,
                    itemBuilder: (ctx, i) => _buildOrderTile(_orders[i]),
                  ),
                ),
    );
  }

  Widget _buildOrderTile(Map<String, dynamic> o) {
    final status = o['status'] ?? 'draft';
    final statusColor = status == 'completed' ? Colors.green : status == 'confirmed' ? Colors.blue : Colors.orange;
    final statusText = status == 'completed' ? 'Bajarilgan' : status == 'confirmed' ? 'Tasdiqlangan' : 'Kutilmoqda';
    final canEdit = o['can_edit'] == true;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _showOrderDetail(o),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor: statusColor.withOpacity(0.12),
                child: Icon(Icons.receipt_long, color: statusColor, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(o['number'] ?? '#${o['id']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(color: statusColor.withOpacity(0.12), borderRadius: BorderRadius.circular(8)),
                          child: Text(statusText, style: TextStyle(color: statusColor, fontSize: 10, fontWeight: FontWeight.w600)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${o['date'] ?? ''} • ${o['created_by'] ?? ''}',
                      style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(_formatMoney((o['total'] ?? 0).toDouble()), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                  if (canEdit)
                    Text('Tahrirlash', style: TextStyle(fontSize: 10, color: Colors.orange[700], fontWeight: FontWeight.w500)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showOrderDetail(Map<String, dynamic> o) {
    final items = List<Map<String, dynamic>>.from(o['items'] ?? []);
    final status = o['status'] ?? 'draft';
    final statusColor = status == 'completed' ? Colors.green : status == 'confirmed' ? Colors.blue : Colors.orange;
    final statusText = status == 'completed' ? 'Bajarilgan' : status == 'confirmed' ? 'Tasdiqlangan' : 'Kutilmoqda';
    final canEdit = o['can_edit'] == true;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.65,
        minChildSize: 0.3,
        maxChildSize: 0.9,
        expand: false,
        builder: (ctx, scroll) => Padding(
          padding: const EdgeInsets.all(16),
          child: ListView(
            controller: scroll,
            children: [
              Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2)))),
              const SizedBox(height: 12),
              // Sarlavha
              Row(children: [
                Expanded(child: Text(o['number'] ?? '', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold))),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: statusColor.withOpacity(0.12), borderRadius: BorderRadius.circular(12)),
                  child: Text(statusText, style: TextStyle(color: statusColor, fontSize: 12, fontWeight: FontWeight.w600)),
                ),
              ]),
              const SizedBox(height: 4),
              Text('${o['date'] ?? ''} • ${o['created_by'] ?? ''}', style: TextStyle(fontSize: 13, color: Colors.grey[600])),
              if ((o['payment_type'] ?? '').isNotEmpty) ...[
                const SizedBox(height: 2),
                Text('To\'lov: ${o['payment_type']}', style: TextStyle(fontSize: 12, color: Colors.grey[600])),
              ],
              const Divider(height: 20),
              // Mahsulotlar
              if (items.isNotEmpty) ...[
                const Text('Buyurtma tarkibi:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 8),
                ...items.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(children: [
                    Expanded(child: Text(item['name'] ?? '', style: const TextStyle(fontSize: 14))),
                    Text('x${(item['quantity'] ?? 0).toDouble().toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(width: 12),
                    SizedBox(
                      width: 80,
                      child: Text(
                        _formatMoney((item['total'] ?? 0).toDouble()),
                        textAlign: TextAlign.right,
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                  ]),
                )),
                const Divider(),
                Row(children: [
                  const Expanded(child: Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                  Text('${_formatMoney((o['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
                ]),
              ],
              if ((o['debt'] ?? 0).toDouble() > 0) ...[
                const SizedBox(height: 8),
                Text('Qarz: ${_formatMoney((o['debt'] ?? 0).toDouble())} so\'m', style: const TextStyle(color: Colors.red, fontSize: 14)),
              ],
              // Tahrirlash tugmasi
              if (canEdit) ...[
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _editOrder(o);
                    },
                    icon: const Icon(Icons.edit, size: 18),
                    label: const Text('Tahrirlash'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.orange,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Center(
                  child: Text('5 daqiqa ichida o\'zgartirish mumkin', style: TextStyle(fontSize: 11, color: Colors.grey[500])),
                ),
              ] else if (status == 'draft') ...[
                const SizedBox(height: 12),
                Center(
                  child: Text(
                    '5 daqiqadan ko\'p o\'tdi. Faqat admin o\'zgartirishi mumkin.',
                    style: TextStyle(fontSize: 12, color: Colors.red[400]),
                    textAlign: TextAlign.center,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _editOrder(Map<String, dynamic> order) async {
    final productsResult = await ApiService.getProducts(widget.token);
    if (!mounted) return;
    final products = List<Map<String, dynamic>>.from(productsResult['products'] ?? []);
    if (products.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulotlar topilmadi')));
      return;
    }
    final result = await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _EditOrderPage(
          order: order,
          products: products,
          token: widget.token,
        ),
      ),
    );
    if (result == true) _loadOrders();
  }

  String _formatMoney(double v) {
    if (v <= 0) return '0';
    final str = v.toInt().toString();
    final buf = StringBuffer();
    for (int i = 0; i < str.length; i++) {
      if (i > 0 && (str.length - i) % 3 == 0) buf.write(' ');
      buf.write(str[i]);
    }
    return buf.toString();
  }
}


// ======================== BUYURTMA TAHRIRLASH ========================

class _EditOrderPage extends StatefulWidget {
  final Map<String, dynamic> order;
  final List<Map<String, dynamic>> products;
  final String token;
  const _EditOrderPage({required this.order, required this.products, required this.token});

  @override
  State<_EditOrderPage> createState() => _EditOrderPageState();
}

class _EditOrderPageState extends State<_EditOrderPage> {
  String _paymentType = 'naqd';
  final Map<int, double> _cart = {};
  bool _isSending = false;
  String _searchQuery = '';

  @override
  void initState() {
    super.initState();
    _paymentType = widget.order['payment_type'] ?? 'naqd';
    // Mavjud mahsulotlarni cartga yuklash
    final items = List<Map<String, dynamic>>.from(widget.order['items'] ?? []);
    for (final item in items) {
      final pid = item['product_id'];
      final qty = (item['quantity'] ?? 0).toDouble();
      if (pid != null && qty > 0) {
        _cart[pid as int] = qty;
      }
    }
  }

  List<Map<String, dynamic>> get _filteredProducts {
    if (_searchQuery.isEmpty) return widget.products;
    final q = _searchQuery.toLowerCase();
    return widget.products.where((p) => (p['name'] ?? '').toString().toLowerCase().contains(q)).toList();
  }

  double get _total {
    double t = 0;
    _cart.forEach((pid, qty) {
      final p = widget.products.firstWhere((x) => x['id'] == pid, orElse: () => {});
      t += (p['price'] ?? 0).toDouble() * qty;
    });
    return t;
  }

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
    final result = await ApiService.updateOrder(widget.token, widget.order['id'] as int, {
      'payment_type': _paymentType,
      'items': items,
    });
    if (!mounted) return;
    setState(() => _isSending = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Buyurtma yangilandi'), backgroundColor: Colors.green));
      Navigator.pop(context, true);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Tahrirlash: ${widget.order['number'] ?? ''}', style: const TextStyle(fontSize: 15)),
        backgroundColor: Colors.orange,
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
                          decoration: BoxDecoration(border: Border.all(color: Colors.orange), borderRadius: BorderRadius.circular(6)),
                          child: Text(
                            qty == qty.roundToDouble() ? qty.toStringAsFixed(0) : qty.toStringAsFixed(1),
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.orange),
                          ),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.add_circle, color: Colors.orange, size: 22),
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
                      Text('${_formatPrice(_total)} so\'m', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const Spacer(),
                  ElevatedButton(
                    onPressed: _isSending ? null : _submit,
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.orange, foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12)),
                    child: _isSending
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Text('Saqlash'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
