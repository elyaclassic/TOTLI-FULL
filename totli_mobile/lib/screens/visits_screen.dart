import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';

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

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;
    final vResult = await ApiService.getVisits(token);
    final pResult = await ApiService.getPartners(token);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (vResult['success'] == true) _visits = List<Map<String, dynamic>>.from(vResult['visits'] ?? []);
        if (pResult['success'] == true) _partners = List<Map<String, dynamic>>.from(pResult['partners'] ?? []);
      });
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
        // Aktiv vizit sahifasini ochish
        _openActiveVisit({
          'id': result['visit_id'],
          'partner_id': partner['id'],
          'partner_name': partner['name'],
          'check_in_time': DateTime.now().toIso8601String(),
          'check_out_time': null,
          'status': 'visited',
        });
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('GPS xato: $e'), backgroundColor: Colors.red));
    }
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
    return Scaffold(
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _visits.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.location_off, size: 64, color: Colors.grey[400]),
                      const SizedBox(height: 16),
                      const Text('Vizitlar yo\'q', style: TextStyle(color: Colors.grey)),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadData,
                  child: ListView.builder(
                    itemCount: _visits.length,
                    itemBuilder: (ctx, i) => _buildVisitTile(_visits[i]),
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

  Future<void> _loadPartnerInfo() async {
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
    final result = await ApiService.checkOut(widget.token, visitId: widget.visit['id']);
    if (!mounted) return;
    setState(() => _isEnding = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit yakunlandi'), backgroundColor: Colors.green));
      Navigator.pop(context);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  void _openCreateOrder() async {
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
          ],
        ),
      ),
    );
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
                      Text('${_formatMoney((d['debt'] ?? 0).toDouble())}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.red)),
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
    if (v >= 1000000) return '${(v / 1000000).toStringAsFixed(1)}M';
    if (v >= 1000) return '${(v / 1000).toStringAsFixed(0)}K';
    return v.toStringAsFixed(0);
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
  final Map<int, int> _cart = {};
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

  Future<void> _submit() async {
    if (_cart.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulot qo\'shing')));
      return;
    }
    setState(() => _isSending = true);
    final items = _cart.entries.map((e) => {'product_id': e.key, 'qty': e.value}).toList();
    final result = await ApiService.createOrder(widget.token, {
      'partner_id': widget.partnerId,
      'payment_type': _paymentType,
      'items': items,
    });
    if (!mounted) return;
    setState(() => _isSending = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Buyurtma: ${result['order_number'] ?? ''}'),
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
                        onPressed: () => setState(() { if (qty <= 1) _cart.remove(pid); else _cart[pid] = qty - 1; }),
                      ),
                      if (qty > 0) Text('$qty', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
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
                      Text('${_cart.values.fold(0, (a, b) => a + b)} ta mahsulot', style: const TextStyle(fontSize: 12, color: Colors.grey)),
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
    if (d >= 1000) return '${(d / 1000).toStringAsFixed(0)}K';
    return d.toStringAsFixed(0);
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
                        if (retQty <= 1) _returnQty.remove(pid); else _returnQty[pid] = retQty - 1;
                      }),
                    ),
                    if (retQty > 0) Text('${retQty.toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.red)),
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
    if (d >= 1000) return '${(d / 1000).toStringAsFixed(0)}K';
    return d.toStringAsFixed(0);
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
    if (v >= 1000000) return '${(v / 1000000).toStringAsFixed(1)}M';
    if (v >= 1000) return '${(v / 1000).toStringAsFixed(0)}K';
    return v.toStringAsFixed(0);
  }
}
