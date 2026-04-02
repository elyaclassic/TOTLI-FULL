import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../services/offline_db_service.dart';
import '../services/sync_service.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  final SessionService _session = SessionService();
  final OfflineDbService _offlineDb = OfflineDbService();
  final SyncService _syncService = SyncService();
  List<Map<String, dynamic>> _orders = [];
  List<Map<String, dynamic>> _offlineOrders = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadOrders();
    _syncService.onStatusChanged = () {
      if (mounted) _loadOrders();
    };
  }

  Future<void> _loadOrders() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();

    // Offline buyurtmalarni har doim yuklash
    // Faqat pending va failed — synced bo'lganlarni ko'rsatmaymiz
    final allOffline = await _offlineDb.getAllOfflineOrders();
    _offlineOrders = allOffline.where((o) => o['status'] != 'synced').toList();

    if (token != null && _syncService.isOnline) {
      try {
        final result = await ApiService.getMyOrders(token).timeout(const Duration(seconds: 10));
        if (mounted) {
          setState(() {
            _isLoading = false;
            if (result['success'] == true) {
              _orders = List<Map<String, dynamic>>.from(result['orders'] ?? []);
            }
          });
        }
      } catch (_) {
        // API xato yoki timeout
        if (mounted) setState(() => _isLoading = false);
      }
    } else {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _createOrder() async {
    final token = await _session.getToken();
    if (token == null) return;

    // Avval cache dan (darhol)
    List<Map<String, dynamic>> products = await _offlineDb.getCachedProducts();
    List<Map<String, dynamic>> partners = await _offlineDb.getCachedPartners();

    // Cache bo'sh va online bo'lsa — serverdan yuklash
    if ((products.isEmpty || partners.isEmpty) && _syncService.isOnline) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Yuklanmoqda...'), duration: Duration(seconds: 3)));
      try {
        final results = await Future.wait([
          ApiService.getProducts(token),
          ApiService.getPartners(token),
        ]).timeout(const Duration(seconds: 5));
        if (!mounted) return;
        final p = List<Map<String, dynamic>>.from(results[0]['products'] ?? []);
        final pr = List<Map<String, dynamic>>.from(results[1]['partners'] ?? []);
        if (p.isNotEmpty) { products = p; _offlineDb.cacheProducts(p); }
        if (pr.isNotEmpty) { partners = pr; _offlineDb.cachePartners(pr); }
      } catch (_) {}
    }

    if (!mounted) return;
    if (products.isEmpty || partners.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Ma\'lumotlar topilmadi. Avval internetga ulanib ilovani oching.'),
        backgroundColor: Colors.red,
        duration: Duration(seconds: 3),
      ));
      return;
    }

    final result = await Navigator.push(context, MaterialPageRoute(
      builder: (_) => _CreateOrderPage(
        products: products,
        partners: partners,
        token: token,
        isOnline: _syncService.isOnline,
      ),
    ));
    if (result == true) _loadOrders();
  }

  Future<void> _showSyncDialog() async {
    final pendingCount = await _offlineDb.getPendingOrderCount();
    if (pendingCount == 0) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Sinxronlash uchun buyurtma yo\'q')),
        );
      }
      return;
    }

    if (!_syncService.isOnline) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Internet yo\'q. Ulanishni tekshiring.'), backgroundColor: Colors.orange),
        );
      }
      return;
    }

    if (!mounted) return;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(children: [
          Icon(Icons.sync, color: Color(0xFF017449)),
          SizedBox(width: 8),
          Text('Sinxronlash'),
        ]),
        content: Text('$pendingCount ta offline buyurtma serverga yuborilsinmi?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keyinroq')),
          ElevatedButton.icon(
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.cloud_upload, size: 18),
            label: const Text('Yuborish'),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449), foregroundColor: Colors.white),
          ),
        ],
      ),
    );

    if (confirm != true || !mounted) return;

    // Progress dialog
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => const AlertDialog(
        content: Row(children: [
          CircularProgressIndicator(),
          SizedBox(width: 16),
          Text('Sinxronlanmoqda...'),
        ]),
      ),
    );

    final result = await _syncService.syncPendingOrders();
    if (!mounted) return;
    Navigator.pop(context); // Progress dialog yopish

    final synced = result['synced'] as int;
    final failed = result['failed'] as int;
    final errors = List<String>.from(result['errors'] ?? []);

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(children: [
          Icon(synced > 0 ? Icons.check_circle : Icons.warning, color: synced > 0 ? Colors.green : Colors.orange),
          const SizedBox(width: 8),
          const Text('Natija'),
        ]),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (synced > 0) Text('$synced ta buyurtma yuborildi', style: const TextStyle(color: Colors.green, fontWeight: FontWeight.bold)),
            if (failed > 0) Text('$failed ta xatolik', style: const TextStyle(color: Colors.red)),
            if (errors.isNotEmpty) ...[
              const SizedBox(height: 8),
              ...errors.take(5).map((e) => Text('• $e', style: const TextStyle(fontSize: 12, color: Colors.red))),
            ],
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('OK')),
        ],
      ),
    );

    _loadOrders();
  }

  @override
  Widget build(BuildContext context) {
    final pendingOffline = _offlineOrders.where((o) => o['status'] == 'pending').toList();
    final hasPending = pendingOffline.isNotEmpty;

    return Scaffold(
      body: Column(
        children: [
          // Offline banner
          if (!_syncService.isOnline)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              color: Colors.orange.shade100,
              child: Row(children: [
                const Icon(Icons.wifi_off, size: 18, color: Colors.orange),
                const SizedBox(width: 8),
                const Expanded(child: Text('Offline rejim — oxirgi ma\'lumotlar', style: TextStyle(fontSize: 13, color: Colors.orange))),
              ]),
            ),
          // Sync banner
          if (hasPending && _syncService.isOnline)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              color: const Color(0xFFE8F5E9),
              child: Row(children: [
                const Icon(Icons.cloud_upload_outlined, size: 18, color: Color(0xFF017449)),
                const SizedBox(width: 8),
                Expanded(child: Text('${pendingOffline.length} ta buyurtma yuborilmagan', style: const TextStyle(fontSize: 13))),
                TextButton.icon(
                  onPressed: _showSyncDialog,
                  icon: const Icon(Icons.sync, size: 16),
                  label: const Text('Sinxronlash'),
                  style: TextButton.styleFrom(
                    foregroundColor: const Color(0xFF017449),
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ]),
            ),
          // Buyurtmalar ro'yxati
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : (_orders.isEmpty && _offlineOrders.isEmpty)
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.shopping_cart_outlined, size: 64, color: Colors.grey[400]),
                            const SizedBox(height: 16),
                            const Text('Buyurtmalar yo\'q', style: TextStyle(color: Colors.grey)),
                          ],
                        ),
                      )
                    : RefreshIndicator(
                        onRefresh: _loadOrders,
                        child: ListView(
                          children: [
                            // Offline buyurtmalar (tepada)
                            if (_offlineOrders.isNotEmpty) ...[
                              const Padding(
                                padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
                                child: Text('Offline buyurtmalar', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Colors.grey)),
                              ),
                              ..._offlineOrders.map((o) => _buildOfflineOrderTile(o)),
                              if (_orders.isNotEmpty) const Divider(height: 24),
                            ],
                            // Server buyurtmalari
                            ..._orders.map((o) => _buildOrderTile(o)),
                          ],
                        ),
                      ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _createOrder,
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add),
        label: Text(_syncService.isOnline ? 'Yangi buyurtma' : 'Offline buyurtma'),
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

  Widget _buildOfflineOrderTile(Map<String, dynamic> o) {
    final status = o['status'] ?? 'pending';
    final Color statusColor;
    final String statusText;
    final IconData statusIcon;
    switch (status) {
      case 'synced':
        statusColor = Colors.green;
        statusText = 'Yuborilgan';
        statusIcon = Icons.cloud_done;
        break;
      case 'failed':
        statusColor = Colors.red;
        statusText = 'Xato';
        statusIcon = Icons.cloud_off;
        break;
      default:
        statusColor = Colors.orange;
        statusText = 'Kutilmoqda';
        statusIcon = Icons.cloud_upload_outlined;
    }

    final items = o['items'] is List ? o['items'] as List : [];
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: statusColor.withOpacity(0.3)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: () => _showOfflineOrderDetail(o),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            CircleAvatar(
              backgroundColor: statusColor.withOpacity(0.15),
              child: Icon(statusIcon, color: statusColor, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text(o['server_number'] ?? 'Offline #${o['local_id']}', style: const TextStyle(fontWeight: FontWeight.w500)),
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(color: statusColor.withOpacity(0.12), borderRadius: BorderRadius.circular(8)),
                  child: Text(statusText, style: TextStyle(color: statusColor, fontSize: 9, fontWeight: FontWeight.w600)),
                ),
              ]),
              Text(o['partner_name'] ?? '', style: const TextStyle(fontSize: 12)),
              if (items.isNotEmpty)
                Text(
                  items.take(3).map((i) => '${i['name'] ?? 'Mahsulot'} x${((i['qty'] ?? 0) as num).toStringAsFixed(0)}').join(', '),
                  style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
            ])),
            Text(_formatMoney((o['total'] ?? 0).toDouble()), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
          ]),
        ),
      ),
    );
  }

  void _showOfflineOrderDetail(Map<String, dynamic> o) {
    final status = o['status'] ?? 'pending';
    final items = o['items'] is List ? o['items'] as List : [];
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.7,
        expand: false,
        builder: (ctx, scroll) => Padding(
          padding: const EdgeInsets.all(16),
          child: ListView(
            controller: scroll,
            children: [
              Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2)))),
              const SizedBox(height: 12),
              Text(o['server_number'] ?? 'Offline #${o['local_id']}', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
              const SizedBox(height: 4),
              Text('${o['partner_name']} • ${o['created_at']?.substring(0, 16) ?? ''}', style: TextStyle(fontSize: 13, color: Colors.grey[600])),
              if (o['error_message'] != null) ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(color: Colors.red.shade50, borderRadius: BorderRadius.circular(8)),
                  child: Text('Xato: ${o['error_message']}', style: const TextStyle(color: Colors.red, fontSize: 12)),
                ),
              ],
              const Divider(height: 20),
              if (items.isNotEmpty) ...[
                ...items.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(children: [
                    Expanded(child: Text(item['name'] ?? 'Mahsulot #${item['product_id']}', style: const TextStyle(fontSize: 14))),
                    Text('x${((item['qty'] ?? 0) as num).toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600)),
                  ]),
                )),
                const Divider(),
              ],
              Row(children: [
                const Expanded(child: Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                Text('${_formatMoney((o['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
              ]),
              const SizedBox(height: 16),
              if (status == 'pending') ...[
                ElevatedButton.icon(
                  onPressed: () async {
                    Navigator.pop(ctx);
                    await _offlineDb.deleteOfflineOrder(o['local_id'] as int);
                    _loadOrders();
                  },
                  icon: const Icon(Icons.delete_outline, size: 18),
                  label: const Text('O\'chirish'),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
                ),
              ],
              if (status == 'failed') ...[
                ElevatedButton.icon(
                  onPressed: () async {
                    Navigator.pop(ctx);
                    await _offlineDb.resetFailedOrder(o['local_id'] as int);
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Qayta urinish uchun belgilandi')));
                    _loadOrders();
                  },
                  icon: const Icon(Icons.refresh, size: 18),
                  label: const Text('Qayta urinish'),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.orange, foregroundColor: Colors.white),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _showOrderDetail(Map<String, dynamic> o) {
    final items = List<Map<String, dynamic>>.from(o['items'] ?? []);
    final status = o['status'] ?? 'draft';
    final statusColor = status == 'completed' ? Colors.green : status == 'confirmed' ? Colors.blue : status == 'cancelled' ? Colors.red : Colors.orange;
    final statusText = status == 'completed' ? 'Bajarilgan' : status == 'confirmed' ? 'Tasdiqlangan' : status == 'cancelled' ? 'Bekor' : 'Kutilmoqda';
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.6,
        minChildSize: 0.3,
        maxChildSize: 0.85,
        expand: false,
        builder: (ctx, scroll) => Padding(
          padding: const EdgeInsets.all(16),
          child: ListView(
            controller: scroll,
            children: [
              Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2)))),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: Text(o['number'] ?? '', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold))),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: statusColor.withOpacity(0.12), borderRadius: BorderRadius.circular(12)),
                  child: Text(statusText, style: TextStyle(color: statusColor, fontSize: 12, fontWeight: FontWeight.w600)),
                ),
              ]),
              const SizedBox(height: 4),
              Text('${o['partner_name'] ?? o['partner'] ?? ''} • ${o['date'] ?? ''}', style: TextStyle(fontSize: 13, color: Colors.grey[600])),
              const Divider(height: 20),
              if (items.isNotEmpty) ...[
                const Text('Buyurtma tarkibi:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 8),
                ...items.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(children: [
                    Expanded(child: Text(item['name'] ?? '', style: const TextStyle(fontSize: 14))),
                    Text('x${(item['quantity'] ?? 0).toDouble().toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(width: 12),
                    SizedBox(width: 80, child: Text(_formatMoney((item['total'] ?? 0).toDouble()), textAlign: TextAlign.right, style: const TextStyle(fontSize: 13))),
                  ]),
                )),
                const Divider(),
                Row(children: [
                  const Expanded(child: Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                  Text('${_formatMoney((o['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
                ]),
              ] else
                Text('${_formatMoney((o['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
              if ((o['debt'] ?? 0).toDouble() > 0) ...[
                const SizedBox(height: 8),
                Text('Qarz: ${_formatMoney((o['debt'] ?? 0).toDouble())} so\'m', style: const TextStyle(color: Colors.red, fontSize: 14)),
              ],
              if (status == 'draft' || status == 'pending') ...[
                const SizedBox(height: 20),
                Row(children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () {
                        Navigator.pop(ctx);
                        _editOrder(o);
                      },
                      icon: const Icon(Icons.edit, size: 18),
                      label: const Text('O\'zgartirish'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFF017449),
                        side: const BorderSide(color: Color(0xFF017449)),
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () {
                        Navigator.pop(ctx);
                        _cancelOrder(o);
                      },
                      icon: const Icon(Icons.cancel_outlined, size: 18),
                      label: const Text('Bekor qilish'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.red,
                        side: const BorderSide(color: Colors.red),
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                ]),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _editOrder(Map<String, dynamic> o) async {
    final token = await _session.getToken();
    if (token == null) return;

    final productsResult = await ApiService.getProducts(token);
    final partnersResult = await ApiService.getPartners(token);
    if (!mounted) return;

    final products = List<Map<String, dynamic>>.from(productsResult['products'] ?? []);
    final partners = List<Map<String, dynamic>>.from(partnersResult['partners'] ?? []);

    final result = await Navigator.push(context, MaterialPageRoute(
      builder: (_) => _CreateOrderPage(
        products: products,
        partners: partners,
        token: token,
        editOrder: o,
        isOnline: _syncService.isOnline,
      ),
    ));
    if (result == true) _loadOrders();
  }

  Future<void> _cancelOrder(Map<String, dynamic> o) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Buyurtmani bekor qilish'),
        content: Text('${o['number']} buyurtmasini bekor qilmoqchimisiz?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Yo\'q')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
            child: const Text('Ha, bekor qilish'),
          ),
        ],
      ),
    );
    if (confirm != true) return;

    final token = await _session.getToken();
    if (token == null) return;
    final result = await ApiService.updateOrder(token, o['id'] as int, {'status': 'cancelled'});
    if (!mounted) return;
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Buyurtma bekor qilindi'), backgroundColor: Colors.green));
      _loadOrders();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  Widget _buildOrderTile(Map<String, dynamic> o) {
    final status = o['status'] ?? 'draft';
    final statusColor = status == 'completed' ? Colors.green : status == 'confirmed' ? Colors.blue : status == 'cancelled' ? Colors.red : Colors.orange;
    final statusText = status == 'completed' ? 'Bajarilgan' : status == 'confirmed' ? 'Tasdiqlangan' : status == 'cancelled' ? 'Bekor' : 'Kutilmoqda';
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: () => _showOrderDetail(o),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(children: [
            CircleAvatar(
              backgroundColor: statusColor.withOpacity(0.15),
              child: Icon(Icons.receipt_long, color: statusColor, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(o['number'] ?? '#${o['id']}', style: const TextStyle(fontWeight: FontWeight.w500)),
              Text(o['partner_name'] ?? o['partner'] ?? '', style: const TextStyle(fontSize: 12)),
              if ((o['items'] ?? []).isNotEmpty)
                Text(
                  (o['items'] as List).take(3).map((i) => '${i['name']} x${(i['quantity'] ?? 0).toDouble().toStringAsFixed(0)}').join(', ') + ((o['items'] as List).length > 3 ? '...' : ''),
                  style: TextStyle(fontSize: 11, color: Colors.grey[600]),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
            ])),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(_formatMoney((o['total'] ?? 0).toDouble()), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
              Text(statusText, style: TextStyle(fontSize: 10, color: statusColor)),
            ]),
          ]),
        ),
      ),
    );
  }
}

class _CreateOrderPage extends StatefulWidget {
  final List<Map<String, dynamic>> products;
  final List<Map<String, dynamic>> partners;
  final String token;
  final Map<String, dynamic>? editOrder;
  final bool isOnline;
  const _CreateOrderPage({required this.products, required this.partners, required this.token, this.editOrder, this.isOnline = true});

  @override
  State<_CreateOrderPage> createState() => _CreateOrderPageState();
}

class _CreateOrderPageState extends State<_CreateOrderPage> {
  final OfflineDbService _offlineDb = OfflineDbService();
  int? _selectedPartnerId;
  String _paymentType = 'naqd';
  final Map<int, double> _cart = {};
  bool _isSending = false;
  String _searchQuery = '';

  bool get _isEdit => widget.editOrder != null;

  @override
  void initState() {
    super.initState();
    if (_isEdit) {
      final o = widget.editOrder!;
      _selectedPartnerId = o['partner_id'] as int?;
      _paymentType = o['payment_type'] ?? 'naqd';
      final items = List<Map<String, dynamic>>.from(o['items'] ?? []);
      for (final item in items) {
        final pid = item['product_id'] as int?;
        if (pid != null) {
          _cart[pid] = (item['quantity'] ?? item['qty'] ?? 0).toDouble();
        }
      }
    }
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
    if (_selectedPartnerId == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mijozni tanlang')));
      return;
    }
    if (_cart.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mahsulot qo\'shing')));
      return;
    }
    setState(() => _isSending = true);

    final items = _cart.entries.map((e) {
      final p = widget.products.firstWhere((x) => x['id'] == e.key, orElse: () => {});
      return {
        'product_id': e.key,
        'qty': e.value,
        'name': p['name'] ?? '',
        'price': (p['price'] ?? 0).toDouble(),
      };
    }).toList();

    if (widget.isOnline) {
      // Online — serverga yuborish
      final serverItems = items.map((e) => {'product_id': e['product_id'], 'qty': e['qty']}).toList();
      final Map<String, dynamic> result;
      if (_isEdit) {
        result = await ApiService.updateOrder(widget.token, widget.editOrder!['id'] as int, {
          'partner_id': _selectedPartnerId,
          'payment_type': _paymentType,
          'items': serverItems,
        });
      } else {
        result = await ApiService.createOrder(widget.token, {
          'partner_id': _selectedPartnerId,
          'payment_type': _paymentType,
          'items': serverItems,
        });
      }
      if (!mounted) return;
      setState(() => _isSending = false);
      if (result['success'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(_isEdit ? 'Buyurtma yangilandi' : 'Buyurtma yaratildi: ${result['order_number'] ?? ''}'),
          backgroundColor: Colors.green,
        ));
        Navigator.pop(context, true);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(result['error'] ?? 'Xato'),
          backgroundColor: Colors.red,
        ));
      }
    } else {
      // Offline — local bazaga saqlash
      final partner = widget.partners.firstWhere((p) => p['id'] == _selectedPartnerId, orElse: () => {});
      await _offlineDb.saveOfflineOrder(
        partnerId: _selectedPartnerId!,
        partnerName: partner['name'] ?? 'Mijoz #$_selectedPartnerId',
        paymentType: _paymentType,
        items: items,
        total: _total,
      );
      if (!mounted) return;
      setState(() => _isSending = false);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Buyurtma offline saqlandi. Internet qaytganda sinxronlanadi.'),
        backgroundColor: Colors.orange,
      ));
      Navigator.pop(context, true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isEdit ? 'Buyurtmani tahrirlash' : (widget.isOnline ? 'Yangi buyurtma' : 'Offline buyurtma')),
        backgroundColor: widget.isOnline ? const Color(0xFF017449) : Colors.orange,
        foregroundColor: Colors.white,
      ),
      body: Column(
        children: [
          if (!widget.isOnline)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              color: Colors.orange.shade50,
              child: const Row(children: [
                Icon(Icons.wifi_off, size: 16, color: Colors.orange),
                SizedBox(width: 8),
                Text('Offline rejim — buyurtma local saqlanadi', style: TextStyle(fontSize: 12, color: Colors.orange)),
              ]),
            ),
          // Mijoz va qidiruv
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              children: [
                DropdownButtonFormField<int>(
                  value: _selectedPartnerId,
                  decoration: InputDecoration(
                    labelText: 'Mijoz',
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                    isDense: true,
                  ),
                  isExpanded: true,
                  items: widget.partners.map((p) => DropdownMenuItem<int>(
                    value: p['id'] as int,
                    child: Text(p['name'] ?? '', overflow: TextOverflow.ellipsis),
                  )).toList(),
                  onChanged: (v) => setState(() => _selectedPartnerId = v),
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
          // Mahsulotlar
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
                    '${_formatMoney((p['price'] ?? 0).toDouble())} | Qoldiq: ${stock.toStringAsFixed(0)} ${p['unit'] ?? ''}',
                    style: TextStyle(fontSize: 11, color: stock > 0 ? Colors.grey : Colors.red),
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (qty > 0) IconButton(icon: const Icon(Icons.remove_circle_outline, size: 22), onPressed: () => setState(() { if (qty <= 1) {
                        _cart.remove(pid);
                      } else {
                        _cart[pid] = qty - 1;
                      } })),
                      if (qty > 0) GestureDetector(
                        onTap: () => _editQty(pid, p['name'] ?? '', qty),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(border: Border.all(color: const Color(0xFF017449)), borderRadius: BorderRadius.circular(6)),
                          child: Text(qty == qty.roundToDouble() ? qty.toStringAsFixed(0) : qty.toStringAsFixed(1), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF017449))),
                        ),
                      ),
                      IconButton(icon: const Icon(Icons.add_circle, color: Color(0xFF017449), size: 22), onPressed: () => setState(() => _cart[pid] = qty + 1)),
                    ],
                  ),
                );
              },
            ),
          ),
          // Jami va yuborish
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
                      Text('${_formatMoney(_total)} so\'m', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const Spacer(),
                  ElevatedButton(
                    onPressed: _isSending ? null : _submit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: widget.isOnline ? const Color(0xFF017449) : Colors.orange,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                    ),
                    child: _isSending
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : Text(widget.isOnline ? 'Yuborish' : 'Saqlash'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
