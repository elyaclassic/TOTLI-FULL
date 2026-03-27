import 'package:flutter/material.dart';
import '../services/session_service.dart';
import '../services/location_service.dart';
import '../services/api_service.dart';
import 'login_screen.dart';
import 'partners_screen.dart';
import 'orders_screen.dart';
import 'visits_screen.dart';
import 'deliveries_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final SessionService _session = SessionService();
  final LocationService _locationService = LocationService();
  String _fullName = '';
  String _role = '';
  bool _isLoading = true;
  String? _lastLocationStatus;
  int _currentTab = 0;

  // Agent stats
  int _partnersCount = 0;
  int _todayOrders = 0;
  double _todayTotal = 0;
  double _totalDebt = 0;

  // Driver stats
  int _pendingDeliveries = 0;
  int _todayDelivered = 0;
  int _totalDeliveries = 0;

  @override
  void initState() {
    super.initState();
    _loadData();
    _startLocationTracking();
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

    if (mounted) setState(() => _isLoading = false);
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
    if (amount >= 1000000) return '${(amount / 1000000).toStringAsFixed(1)}M';
    if (amount >= 1000) return '${(amount / 1000).toStringAsFixed(0)}K';
    return amount.toStringAsFixed(0);
  }

  @override
  Widget build(BuildContext context) {
    final isAgent = _role == 'agent';
    return Scaffold(
      appBar: AppBar(
        title: Text(_fullName),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
        actions: [
          if (_lastLocationStatus != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Center(
                child: Text(_lastLocationStatus!, style: const TextStyle(fontSize: 12, color: Color(0xFFFFB50D))),
              ),
            ),
          IconButton(icon: const Icon(Icons.my_location), onPressed: _sendLocationNow, tooltip: 'GPS yuborish'),
          IconButton(icon: const Icon(Icons.logout), onPressed: _logout, tooltip: 'Chiqish'),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadData,
              child: IndexedStack(
                index: _currentTab,
                children: isAgent
                    ? [_buildAgentHome(), const PartnersScreen(), const OrdersScreen(), const VisitsScreen()]
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
                BottomNavigationBarItem(icon: Icon(Icons.location_on), label: 'Vizitlar'),
              ]
            : const [
                BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Asosiy'),
                BottomNavigationBarItem(icon: Icon(Icons.local_shipping), label: 'Yetkazishlar'),
              ],
      ),
    );
  }

  Widget _buildStatCard(String title, String value, IconData icon, Color color) {
    return Expanded(
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
    );
  }

  Widget _buildAgentHome() {
    return SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            _buildStatCard('Mijozlar', '$_partnersCount', Icons.people, Colors.blue),
            _buildStatCard('Bugun', '$_todayOrders ta', Icons.shopping_cart, Colors.green),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            _buildStatCard('Bugun summa', _formatMoney(_todayTotal), Icons.attach_money, Colors.orange),
            _buildStatCard('Jami qarz', _formatMoney(_totalDebt), Icons.account_balance, Colors.red),
          ]),
          const SizedBox(height: 20),
          _buildActionTile('Yangi buyurtma', Icons.add_shopping_cart, Colors.green, () {
            setState(() => _currentTab = 2);
          }),
          _buildActionTile('Vizit boshlash', Icons.pin_drop, Colors.blue, () {
            setState(() => _currentTab = 3);
          }),
          _buildActionTile('Yangi mijoz qo\'shish', Icons.person_add, Colors.purple, () {
            setState(() => _currentTab = 1);
          }),
        ],
      ),
    );
  }

  Widget _buildDriverHome() {
    return SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            _buildStatCard('Kutilmoqda', '$_pendingDeliveries', Icons.pending_actions, Colors.orange),
            _buildStatCard('Bugun yetkazildi', '$_todayDelivered', Icons.check_circle, Colors.green),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            _buildStatCard('Jami yetkazishlar', '$_totalDeliveries', Icons.local_shipping, Colors.blue),
            _buildStatCard('GPS', _lastLocationStatus ?? 'Faol', Icons.gps_fixed, Colors.teal),
          ]),
          const SizedBox(height: 20),
          _buildActionTile('Yetkazishlarni ko\'rish', Icons.list_alt, Colors.blue, () {
            setState(() => _currentTab = 1);
          }),
        ],
      ),
    );
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
