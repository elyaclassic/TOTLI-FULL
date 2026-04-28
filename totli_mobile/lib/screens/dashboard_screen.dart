import 'package:flutter/material.dart';
import '../services/session_service.dart';
import '../services/location_service.dart';
import '../services/api_service.dart';
import '../services/sync_service.dart';
import '../services/offline_db_service.dart';
import 'login_screen.dart';
import 'partners_screen.dart';
import 'orders_screen.dart';
import 'visits_screen.dart';
import 'kassa_screen.dart';
import 'deliveries_screen.dart';
import 'map_screen.dart';
import 'driver_map_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final SessionService _session = SessionService();
  final LocationService _locationService = LocationService();
  final SyncService _syncService = SyncService();
  final OfflineDbService _offlineDb = OfflineDbService();
  String _fullName = '';
  String _role = '';
  bool _isLoading = true;
  String? _lastLocationStatus;
  int _currentTab = 0;
  int _pendingOfflineOrders = 0;

  // Agent stats
  int _partnersCount = 0;
  int _todayOrders = 0;
  double _todayTotal = 0;
  double _totalDebt = 0;

  // Oylik savdo rejasi
  double _monthlySold = 0;
  double _monthlyTarget = 0;
  double _monthlyPercent = 0;

  // Driver stats
  int _pendingDeliveries = 0;
  int _todayDelivered = 0;
  int _totalDeliveries = 0;

  @override
  void initState() {
    super.initState();
    _loadData();
    _startLocationTracking();
    _syncService.onStatusChanged = () {
      if (mounted) {
        _loadPendingCount();
        setState(() {});
      }
    };
  }

  Future<void> _startLocationTracking() async {
    final hasPerm = await _locationService.checkPermission();
    if (hasPerm) {
      _locationService.startPeriodicTracking();
    }
  }

  Future<void> _loadData() async {
    final name = await _session.getFullName();
    final role = await _session.getRole();
    final token = await _session.getToken();
    setState(() {
      _fullName = name ?? 'Foydalanuvchi';
      _role = role ?? 'agent';
    });

    if (token != null) {
      if (_role == 'agent') {
        final stats = await ApiService.getAgentStats(token);
        if (stats['success'] == true && mounted) {
          final s = stats['stats'] as Map<String, dynamic>? ?? {};
          setState(() {
            _partnersCount = s['partners_count'] ?? 0;
            _todayOrders = s['today_orders'] ?? 0;
            _todayTotal = (s['today_total'] ?? 0).toDouble();
            _totalDebt = (s['total_debt'] ?? 0).toDouble();
          });
        }
        // Oylik savdo rejasi
        final kpi = await ApiService.getAgentKpi(token, period: 'monthly');
        if (kpi['success'] == true && mounted) {
          final m = kpi['metrics'] as Map<String, dynamic>? ?? {};
          setState(() {
            _monthlySold = (m['orders_total'] ?? 0).toDouble();
            _monthlyTarget = (m['sales_target'] ?? 0).toDouble();
            _monthlyPercent = (m['sales_percent'] ?? 0).toDouble();
          });
        }
      } else if (_role == 'driver') {
        final stats = await ApiService.getDriverStats(token);
        if (stats['success'] == true && mounted) {
          final s = stats['stats'] as Map<String, dynamic>? ?? {};
          setState(() {
            _pendingDeliveries = s['pending'] ?? 0;
            _todayDelivered = s['today_delivered'] ?? 0;
            _totalDeliveries = s['total'] ?? 0;
          });
        }
      }
    }

    await _loadPendingCount();
    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _loadPendingCount() async {
    final count = await _offlineDb.getPendingOrderCount();
    if (mounted) setState(() => _pendingOfflineOrders = count);
  }

  Future<void> _sendLocationNow() async {
    setState(() => _lastLocationStatus = 'Yuborilmoqda...');
    final ok = await _locationService.sendLocation();
    if (mounted) {
      setState(() => _lastLocationStatus = ok
          ? 'Yuborildi!'
          : _locationService.lastError ?? 'Xato');
      Future.delayed(const Duration(seconds: 3), () {
        if (mounted) {
          setState(() => _lastLocationStatus =
              _locationService.isTracking ? 'GPS faol' : null);
        }
      });
    }
  }

  Future<void> _logout() async {
    _locationService.stopPeriodicTracking();
    await _session.logout();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
  }

  String _formatMoney(double amount) {
    final s = amount.toStringAsFixed(0);
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0 && s[i] != '-') buf.write(',');
      buf.write(s[i]);
    }
    return buf.toString();
  }

  @override
  Widget build(BuildContext context) {
    final isAgent = _role == 'agent';
    return WillPopScope(
      onWillPop: () async {
        if (_currentTab != 0) {
          setState(() => _currentTab = 0);
          return false;
        }
        return true;
      },
      child: Scaffold(
      appBar: AppBar(
        title: Row(children: [
          if (!_syncService.isOnline)
            const Padding(
              padding: EdgeInsets.only(right: 6),
              child: Icon(Icons.wifi_off, size: 16, color: Colors.orange),
            ),
          Flexible(child: Text(_fullName, overflow: TextOverflow.ellipsis)),
        ]),
        backgroundColor: _syncService.isOnline ? const Color(0xFF017449) : Colors.orange.shade800,
        foregroundColor: Colors.white,
        actions: [
          if (_pendingOfflineOrders > 0 && _syncService.isOnline)
            IconButton(
              icon: Badge(
                label: Text('$_pendingOfflineOrders', style: const TextStyle(fontSize: 10)),
                child: const Icon(Icons.cloud_upload),
              ),
              onPressed: () => setState(() => _currentTab = 2), // Buyurtmalar tabiga o'tish
              tooltip: 'Sinxronlash kerak',
            ),
          if (_lastLocationStatus != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Center(
                child: Text(_lastLocationStatus!, style: const TextStyle(fontSize: 11, color: Color(0xFFFFB50D))),
              ),
            ),
          IconButton(icon: const Icon(Icons.my_location, size: 20), onPressed: _sendLocationNow, tooltip: 'GPS yuborish'),
          IconButton(icon: const Icon(Icons.logout, size: 20), onPressed: _logout, tooltip: 'Chiqish'),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadData,
              child: IndexedStack(
                index: _currentTab,
                children: isAgent
                    ? [_buildAgentHome(), const PartnersScreen(), const OrdersScreen(), const KassaScreen(), const VisitsScreen()]
                    : [_buildDriverHome(), const DeliveriesScreen()],
              ),
            ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentTab,
        onTap: (i) => setState(() => _currentTab = i),
        type: BottomNavigationBarType.fixed,
        selectedItemColor: const Color(0xFF017449),
        unselectedItemColor: Colors.grey,
        items: isAgent
            ? const [
                BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Asosiy'),
                BottomNavigationBarItem(icon: Icon(Icons.people), label: 'Mijozlar'),
                BottomNavigationBarItem(icon: Icon(Icons.shopping_cart), label: 'Buyurtmalar'),
                BottomNavigationBarItem(icon: Icon(Icons.account_balance_wallet), label: 'Kassa'),
                BottomNavigationBarItem(icon: Icon(Icons.location_on), label: 'Vizitlar'),
              ]
            : const [
                BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Asosiy'),
                BottomNavigationBarItem(icon: Icon(Icons.local_shipping), label: 'Yetkazishlar'),
              ],
      ),
    ));
  }

  Widget _buildStatCard(String title, String value, IconData icon, Color color, {VoidCallback? onTap}) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: Card(
          elevation: 2,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              children: [
                Icon(icon, color: color, size: 28),
                const SizedBox(height: 6),
                Text(value, style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: color)),
                const SizedBox(height: 2),
                Text(title, style: const TextStyle(fontSize: 11, color: Colors.grey), textAlign: TextAlign.center),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _showDebtors() async {
    final token = await _session.getToken();
    if (token == null) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        maxChildSize: 0.9,
        minChildSize: 0.4,
        expand: false,
        builder: (ctx, scrollController) => FutureBuilder<Map<String, dynamic>>(
          future: ApiService.getAgentDebtors(token).timeout(const Duration(seconds: 10)),
          builder: (ctx, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            final data = snap.data;
            if (data == null || data['success'] != true) {
              return const Center(child: Text('Ma\'lumot yuklanmadi'));
            }
            final debtors = List<Map<String, dynamic>>.from(data['debtors'] ?? []);
            final total = (data['total'] ?? 0).toDouble();
            return Column(children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(children: [
                  const Icon(Icons.account_balance, color: Colors.red),
                  const SizedBox(width: 8),
                  const Expanded(child: Text('Qarzdorlar', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold))),
                  Text(_formatMoney(total), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.red)),
                ]),
              ),
              const Divider(height: 1),
              if (debtors.isEmpty)
                const Padding(padding: EdgeInsets.all(32), child: Text('Qarzdor yo\'q', style: TextStyle(color: Colors.grey)))
              else
                Expanded(
                  child: ListView.separated(
                    controller: scrollController,
                    itemCount: debtors.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (ctx, i) {
                      final d = debtors[i];
                      return ListTile(
                        leading: CircleAvatar(
                          backgroundColor: Colors.red.shade50,
                          child: Text('${i + 1}', style: TextStyle(color: Colors.red.shade700, fontWeight: FontWeight.bold)),
                        ),
                        title: Text(d['name'] ?? '', style: const TextStyle(fontWeight: FontWeight.w500)),
                        subtitle: d['phone'] != '' ? Text(d['phone']) : null,
                        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                          Text(_formatMoney((d['debt'] ?? 0).toDouble()),
                            style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.red, fontSize: 15)),
                          const SizedBox(width: 4),
                          const Icon(Icons.chevron_right, color: Colors.grey, size: 20),
                        ]),
                        onTap: () {
                          Navigator.pop(ctx);
                          _showPartnerDebts(token!, d['id'] as int, d['name'] ?? '', (d['debt'] ?? 0).toDouble());
                        },
                      );
                    },
                  ),
                ),
            ]);
          },
        ),
      ),
    );
  }

  void _showPartnerDebts(String token, int partnerId, String partnerName, double totalDebt) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        maxChildSize: 0.9,
        minChildSize: 0.4,
        expand: false,
        builder: (ctx, scrollController) => FutureBuilder<Map<String, dynamic>>(
          future: ApiService.getPartnerDebts(token, partnerId).timeout(const Duration(seconds: 10)),
          builder: (ctx, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            final data = snap.data;
            final debts = List<Map<String, dynamic>>.from(data?['debts'] ?? []);
            return Column(children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const Icon(Icons.store, color: Colors.blue),
                    const SizedBox(width: 8),
                    Expanded(child: Text(partnerName, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold))),
                  ]),
                  const SizedBox(height: 8),
                  Row(children: [
                    const Text('Jami qarz: ', style: TextStyle(fontSize: 14, color: Colors.grey)),
                    Text(_formatMoney(totalDebt), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.red)),
                  ]),
                ]),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView(
                  controller: scrollController,
                  children: [
                    // Qarzli buyurtmalar
                    if (debts.isNotEmpty) ...[
                      const Padding(padding: EdgeInsets.fromLTRB(16, 8, 16, 4),
                        child: Text('Qarzli buyurtmalar', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.red))),
                      ...debts.map((o) {
                        final date = (o['date'] ?? '').toString();
                        final number = o['number'] ?? '';
                        final total = (o['total'] ?? 0).toDouble();
                        final debt = (o['debt'] ?? 0).toDouble();
                        final paid = total - debt;
                        return ListTile(
                          dense: true,
                          title: Text(number, style: const TextStyle(fontWeight: FontWeight.w500, fontSize: 14)),
                          subtitle: Text(date, style: const TextStyle(fontSize: 12)),
                          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                            Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text(_formatMoney(debt), style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.red, fontSize: 14)),
                              ],
                            ),
                            const SizedBox(width: 4),
                            const Icon(Icons.chevron_right, color: Colors.grey, size: 18),
                          ]),
                          onTap: () => _showOrderDetail(o),
                        );
                      }),
                    ],
                    // To'lov tarixi
                    ..._buildPaymentHistory(data),
                  ],
                ),
              ),
            ]);
          },
        ),
      ),
    );
  }

  List<Widget> _buildPaymentHistory(Map<String, dynamic>? data) {
    final payments = List<Map<String, dynamic>>.from(data?['payments'] ?? []);
    if (payments.isEmpty) return [];
    final payTypeLabel = {'naqd': 'Naqd', 'plastik': 'Plastik', 'perechisleniye': 'Per.'};
    return [
      const Divider(height: 20),
      Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
        child: Row(children: [
          const Icon(Icons.receipt_long, size: 16, color: Colors.green),
          const SizedBox(width: 6),
          const Text('To\'lov tarixi', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.green)),
        ])),
      ...payments.map((p) => ListTile(
        dense: true,
        leading: Icon(
          p['payment_type'] == 'plastik' ? Icons.credit_card : p['payment_type'] == 'perechisleniye' ? Icons.account_balance : Icons.money,
          color: Colors.green, size: 20,
        ),
        title: Text(p['number'] ?? '', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(p['date'] ?? '', style: const TextStyle(fontSize: 11)),
          if ((p['description'] ?? '').toString().isNotEmpty)
            Text(p['description'], style: const TextStyle(fontSize: 11, color: Colors.grey), maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(_formatMoney((p['amount'] ?? 0).toDouble()), style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.green, fontSize: 14)),
          Text(payTypeLabel[p['payment_type']] ?? p['payment_type'] ?? '', style: const TextStyle(fontSize: 10, color: Colors.grey)),
        ]),
      )),
    ];
  }

  void _showOrderDetail(Map<String, dynamic> order) {
    final items = List<Map<String, dynamic>>.from(order['items'] ?? []);
    final number = order['number'] ?? '';
    final date = order['date'] ?? '';
    final total = (order['total'] ?? 0).toDouble();
    final debt = (order['debt'] ?? 0).toDouble();
    final paid = total - debt;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(number, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        content: SingleChildScrollView(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(date, style: TextStyle(color: Colors.grey[600], fontSize: 13)),
            const SizedBox(height: 12),
            if (items.isEmpty)
              const Text('Mahsulotlar topilmadi', style: TextStyle(color: Colors.grey))
            else
              ...items.map((item) {
                final qty = (item['quantity'] ?? 0).toDouble();
                final price = (item['price'] ?? 0).toDouble();
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(children: [
                    Expanded(child: Text(item['name'] ?? '', style: const TextStyle(fontSize: 14))),
                    Text('x${qty.toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w500, fontSize: 13)),
                    const SizedBox(width: 8),
                    SizedBox(width: 80, child: Text(_formatMoney(qty * price), textAlign: TextAlign.right, style: const TextStyle(fontSize: 13))),
                  ]),
                );
              }),
            const Divider(height: 16),
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              const Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold)),
              Text(_formatMoney(total), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            ]),
            if (paid > 0) ...[
              const SizedBox(height: 4),
              Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                const Text('To\'langan:', style: TextStyle(color: Colors.green)),
                Text(_formatMoney(paid), style: const TextStyle(color: Colors.green)),
              ]),
            ],
            const SizedBox(height: 4),
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              const Text('Qarz:', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
              Text(_formatMoney(debt), style: const TextStyle(color: Colors.red, fontWeight: FontWeight.bold, fontSize: 16)),
            ]),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Yopish')),
        ],
      ),
    );
  }

  Widget _buildSalesPlanCard() {
    if (_monthlyTarget <= 0) {
      return Card(
        elevation: 2,
        color: Colors.grey[50],
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            Icon(Icons.flag_outlined, color: Colors.grey[500], size: 28),
            const SizedBox(width: 12),
            Expanded(child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Oylik reja', style: TextStyle(fontSize: 12, color: Colors.grey[600])),
                Text('Bu oyda reja qo\'yilmagan', style: TextStyle(fontSize: 14, color: Colors.grey[700])),
              ],
            )),
          ]),
        ),
      );
    }
    final pct = _monthlyPercent.clamp(0, 200) / 100;
    final color = _monthlyPercent >= 100
        ? Colors.green
        : _monthlyPercent >= 70
            ? Colors.orange
            : Colors.red;
    final remaining = (_monthlyTarget - _monthlySold).clamp(0, double.infinity).toDouble();
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(Icons.flag, color: color, size: 22),
              const SizedBox(width: 8),
              const Text('Oylik savdo rejasi', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text('${_monthlyPercent.toStringAsFixed(1)}%',
                    style: TextStyle(fontSize: 13, color: color, fontWeight: FontWeight.bold)),
              ),
            ]),
            const SizedBox(height: 10),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                value: pct > 1 ? 1.0 : pct.toDouble(),
                minHeight: 12,
                backgroundColor: Colors.grey[200],
                valueColor: AlwaysStoppedAnimation<Color>(color),
              ),
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Sotgan', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                  Text(_formatMoney(_monthlySold), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
                ]),
                Column(crossAxisAlignment: CrossAxisAlignment.center, children: [
                  Text('Reja', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                  Text(_formatMoney(_monthlyTarget), style: const TextStyle(fontSize: 13)),
                ]),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('Qoldi', style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                  Text(remaining == 0 ? '✓ Bajarildi' : _formatMoney(remaining),
                      style: TextStyle(fontSize: 13, color: remaining == 0 ? Colors.green : null,
                          fontWeight: remaining == 0 ? FontWeight.bold : FontWeight.normal)),
                ]),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAgentHome() {
    return RefreshIndicator(
      onRefresh: _loadData,
      child: SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            _buildStatCard('Mijozlar', '$_partnersCount', Icons.people, Colors.blue, onTap: () => setState(() => _currentTab = 1)),
            _buildStatCard('Bugun', '$_todayOrders ta', Icons.shopping_cart, Colors.green, onTap: () => setState(() => _currentTab = 2)),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            _buildStatCard('Bugun summa', _formatMoney(_todayTotal), Icons.attach_money, Colors.orange, onTap: () => setState(() => _currentTab = 2)),
            _buildStatCard('Jami qarz', _formatMoney(_totalDebt), Icons.account_balance, Colors.red, onTap: _showDebtors),
          ]),
          const SizedBox(height: 12),
          _buildSalesPlanCard(),
          const SizedBox(height: 20),
          _buildActionTile('Yangi buyurtma', Icons.add_shopping_cart, Colors.green, () {
            setState(() => _currentTab = 2);
          }),
          _buildActionTile('Vizit boshlash', Icons.pin_drop, Colors.blue, () {
            setState(() => _currentTab = 4);
          }),
          _buildActionTile('Xarita — barcha mijozlar', Icons.map, Colors.orange, () {
            Navigator.push(context, MaterialPageRoute(builder: (_) => const MapScreen()));
          }),
          _buildActionTile('Yangi mijoz qo\'shish', Icons.person_add, Colors.purple, () {
            setState(() => _currentTab = 1);
          }),
        ],
      ),
    ));
  }

  Widget _buildDriverHome() {
    return RefreshIndicator(
      onRefresh: _loadData,
      child: SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            _buildStatCard('Kutilmoqda', '$_pendingDeliveries', Icons.pending_actions, Colors.orange, onTap: () => setState(() => _currentTab = 1)),
            _buildStatCard('Bugun yetkazildi', '$_todayDelivered', Icons.check_circle, Colors.green, onTap: () => setState(() => _currentTab = 1)),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            _buildStatCard('Jami yetkazishlar', '$_totalDeliveries', Icons.local_shipping, Colors.blue, onTap: () => setState(() => _currentTab = 1)),
            _buildStatCard('GPS', _lastLocationStatus ?? 'Faol', Icons.gps_fixed, Colors.teal, onTap: () {
              _locationService.sendLocation().then((_) { if (mounted) setState(() {}); });
            }),
          ]),
          const SizedBox(height: 20),
          _buildActionTile('Yetkazishlarni ko\'rish', Icons.list_alt, Colors.blue, () {
            setState(() => _currentTab = 1);
          }),
          _buildActionTile('Xarita — yetkazishlar', Icons.map, Colors.orange, () {
            Navigator.push(context, MaterialPageRoute(builder: (_) => const DriverMapScreen()));
          }),
        ],
      ),
    ));
  }

  Widget _buildActionTile(String title, IconData icon, Color color, VoidCallback onTap) {
    return Card(
      elevation: 2,
      margin: const EdgeInsets.only(bottom: 8),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: ListTile(
        leading: CircleAvatar(backgroundColor: color.withOpacity(0.15), child: Icon(icon, color: color)),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w500)),
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
