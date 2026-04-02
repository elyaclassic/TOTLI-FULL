import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/offline_db_service.dart';
import '../services/location_service.dart';

class DeliveriesScreen extends StatefulWidget {
  const DeliveriesScreen({super.key});
  @override
  State<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends State<DeliveriesScreen> {
  final SessionService _session = SessionService();
  final SyncService _syncService = SyncService();
  final OfflineDbService _offlineDb = OfflineDbService();
  List<Map<String, dynamic>> _deliveries = [];
  bool _isLoading = true;
  int _pendingActions = 0;

  @override
  void initState() {
    super.initState();
    _syncService.onStatusChanged = () {
      if (mounted) setState(() {});
    };
    _load();
  }

  Future<void> _load() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;

    _pendingActions = await _offlineDb.getPendingDeliveryActionCount();

    if (_syncService.isOnline) {
      // Online — sinxronlash keyin serverdan yuklash
      if (_pendingActions > 0) {
        await _syncService.syncPendingDeliveries();
        _pendingActions = await _offlineDb.getPendingDeliveryActionCount();
      }
      final r = await ApiService.getDeliveries(token);
      if (r['success'] == true) {
        _deliveries = List<Map<String, dynamic>>.from(r['deliveries'] ?? []);
        // Cache ga saqlash
        _offlineDb.cacheDeliveries(_deliveries);
      }
    } else {
      // Offline — cache dan o'qish
      _deliveries = await _offlineDb.getCachedDeliveries();
    }

    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _syncNow() async {
    if (!_syncService.isOnline) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Internet yo\'q'), backgroundColor: Colors.orange));
      return;
    }
    setState(() => _isLoading = true);
    final result = await _syncService.syncPendingDeliveries();
    final synced = result['synced'] ?? 0;
    final failed = result['failed'] ?? 0;
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Sinxronlandi: $synced, Xato: $failed'),
        backgroundColor: failed > 0 ? Colors.orange : Colors.green,
      ));
    }
    await _load();
  }

  String _sLabel(String s) { switch (s) { case 'in_progress': return 'Yo\'lda'; case 'delivered': return 'Yetkazildi'; case 'failed': return 'Qaytdi'; default: return 'Kutilmoqda'; } }
  Color _sColor(String s) { switch (s) { case 'in_progress': return Colors.blue; case 'delivered': return Colors.green; case 'failed': return Colors.red; default: return Colors.orange; } }
  String _fmt(double v) { if (v <= 0) return '0'; final s = v.toInt().toString(); final b = StringBuffer(); for (int i = 0; i < s.length; i++) { if (i > 0 && (s.length - i) % 3 == 0) b.write(' '); b.write(s[i]); } return b.toString(); }

  @override
  Widget build(BuildContext context) {
    final active = _deliveries.where((d) => !['delivered', 'failed'].contains(d['status'])).toList();
    final done = _deliveries.where((d) => ['delivered', 'failed'].contains(d['status'])).toList();
    return _isLoading
        ? const Center(child: CircularProgressIndicator())
        : _deliveries.isEmpty
            ? Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                if (!_syncService.isOnline) ...[
                  const Icon(Icons.wifi_off, size: 48, color: Colors.orange),
                  const SizedBox(height: 8),
                  const Text('Offline rejim', style: TextStyle(color: Colors.orange, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text('Avval internetga ulanib ma\'lumotlarni yuklang', style: TextStyle(color: Colors.grey[600], fontSize: 13)),
                ] else ...[
                  Icon(Icons.local_shipping_outlined, size: 64, color: Colors.grey[400]), const SizedBox(height: 16),
                  const Text('Yetkazishlar yo\'q', style: TextStyle(color: Colors.grey)),
                ],
              ]))
            : RefreshIndicator(onRefresh: _load, child: ListView(children: [
                // Offline banner
                if (!_syncService.isOnline)
                  Container(
                    color: Colors.orange.shade50,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Row(children: [
                      const Icon(Icons.wifi_off, size: 18, color: Colors.orange),
                      const SizedBox(width: 8),
                      const Expanded(child: Text('Offline rejim — cache ma\'lumotlar', style: TextStyle(fontSize: 13, color: Colors.orange))),
                    ]),
                  ),
                // Sync banner
                if (_pendingActions > 0 && _syncService.isOnline)
                  Container(
                    color: Colors.blue.shade50,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                    child: Row(children: [
                      const Icon(Icons.sync, size: 18, color: Colors.blue),
                      const SizedBox(width: 8),
                      Expanded(child: Text('$_pendingActions ta yetkazish yuborilmagan', style: const TextStyle(fontSize: 13))),
                      TextButton(onPressed: _syncNow, child: const Text('Sinxronlash')),
                    ]),
                  ),
                if (active.isNotEmpty) ...[
                  Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 4), child: Text('Faol (${active.length})', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold))),
                  ...active.map(_tile),
                ],
                if (done.isNotEmpty) ...[
                  Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 4), child: Text('Yakunlangan (${done.length})', style: TextStyle(fontSize: 13, color: Colors.grey[600]))),
                  ...done.map(_tile),
                ],
                const SizedBox(height: 20),
              ]));
  }

  Widget _tile(Map<String, dynamic> d) {
    final status = d['status'] ?? 'pending';
    final color = _sColor(status);
    final isActive = !['delivered', 'failed'].contains(status);
    final items = List<Map<String, dynamic>>.from(d['items'] ?? []);
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10), side: isActive ? BorderSide(color: color.withOpacity(0.3)) : BorderSide.none),
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: () async {
          final result = await Navigator.push(context, MaterialPageRoute(builder: (_) => _DeliveryDetailPage(delivery: d)));
          if (result == true) _load();
        },
        child: Padding(padding: const EdgeInsets.all(12), child: Row(children: [
          Icon(Icons.local_shipping, color: color, size: 22),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(d['partner_name'] ?? '', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
            Text(d['partner_address'] ?? d['delivery_address'] ?? '', style: TextStyle(fontSize: 12, color: Colors.grey[600]), maxLines: 1, overflow: TextOverflow.ellipsis),
            if (items.isNotEmpty)
              Text('${items.length} ta mahsulot', style: TextStyle(fontSize: 11, color: Colors.grey[500])),
          ])),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(_fmt((d['total'] ?? 0).toDouble()), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: color.withOpacity(0.1), borderRadius: BorderRadius.circular(8)),
              child: Text(_sLabel(status), style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w600)),
            ),
            if (status == 'delivered' && (d['debt'] ?? 0).toDouble() > 0)
              Text('Qarz: ${_fmt((d['debt'] ?? 0).toDouble())}', style: const TextStyle(fontSize: 10, color: Colors.red)),
            if (status == 'delivered' && (d['paid'] ?? 0).toDouble() > 0 && (d['debt'] ?? 0).toDouble() <= 0)
              const Text('To\'langan', style: TextStyle(fontSize: 10, color: Colors.green)),
          ]),
        ])),
      ),
    );
  }
}


// ==================== BUYURTMA TAFSILOT SAHIFASI ====================

class _DeliveryDetailPage extends StatefulWidget {
  final Map<String, dynamic> delivery;
  const _DeliveryDetailPage({required this.delivery});
  @override
  State<_DeliveryDetailPage> createState() => _DeliveryDetailPageState();
}

class _DeliveryDetailPageState extends State<_DeliveryDetailPage> {
  final SessionService _session = SessionService();
  final OfflineDbService _offlineDb = OfflineDbService();
  late Map<String, dynamic> _d;
  bool _isBusy = false;

  @override
  void initState() { super.initState(); _d = Map<String, dynamic>.from(widget.delivery); }

  String _fmt(double v) { if (v <= 0) return '0'; final s = v.toInt().toString(); final b = StringBuffer(); for (int i = 0; i < s.length; i++) { if (i > 0 && (s.length - i) % 3 == 0) b.write(' '); b.write(s[i]); } return b.toString(); }

  double _calcTotal() {
    final items = List<Map<String, dynamic>>.from(_d['items'] ?? []);
    double t = 0;
    for (final item in items) {
      t += (item['quantity'] ?? 0).toDouble() * (item['price'] ?? 0).toDouble();
    }
    return t > 0 ? t : (_d['total'] ?? 0).toDouble();
  }

  void _editItemQty(int index, String name, double currentQty) async {
    final controller = TextEditingController(text: currentQty.toStringAsFixed(0));
    final result = await showDialog<double>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(name, style: const TextStyle(fontSize: 15)),
        content: TextField(
          controller: controller,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Miqdor', border: OutlineInputBorder(), hintText: '0 = o\'chirish'),
          onSubmitted: (v) => Navigator.pop(ctx, double.tryParse(v)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, 0.0),
            child: const Text('O\'chirish', style: TextStyle(color: Colors.red)),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, double.tryParse(controller.text)),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF017449)),
            child: const Text('OK', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
    if (result == null) return;
    setState(() {
      final items = List<Map<String, dynamic>>.from(_d['items'] ?? []);
      if (result <= 0) {
        items.removeAt(index);
      } else {
        items[index] = Map<String, dynamic>.from(items[index]);
        items[index]['quantity'] = result;
        items[index]['total'] = result * (items[index]['price'] ?? 0).toDouble();
      }
      _d['items'] = items;
      _d['total'] = _calcTotal();
    });
  }

  Future<void> _doAction(String newStatus, {double? paidAmount, double? naqdAmount, double? plastikAmount}) async {
    setState(() => _isBusy = true);
    final token = await _session.getToken();
    if (token == null) return;
    double? lat, lng;
    try {
      final pos = await LocationService().getPosition();
      lat = pos.latitude; lng = pos.longitude;
    } catch (_) {}
    // To'lov ma'lumotlari
    final naqd = naqdAmount ?? paidAmount ?? 0;
    final plastik = plastikAmount ?? 0;
    String? notes;
    if (naqd > 0 || plastik > 0) {
      final parts = <String>[];
      if (naqd > 0) parts.add('Naqd: ${naqd.toInt()}');
      if (plastik > 0) parts.add('Plastik: ${plastik.toInt()}');
      notes = parts.join(', ');
    }

    final syncService = SyncService();
    if (!syncService.isOnline) {
      // Offline — lokal bazaga saqlash
      await _offlineDb.saveOfflineDeliveryAction(
        deliveryId: _d['id'] as int,
        partnerName: (_d['partner_name'] ?? '').toString(),
        newStatus: newStatus,
        latitude: lat,
        longitude: lng,
        notes: notes,
      );
      // Cache dagi statusni ham yangilash
      await _offlineDb.updateCachedDeliveryStatus(_d['id'] as int, newStatus);

      if (!mounted) return;
      setState(() => _isBusy = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(newStatus == 'delivered'
            ? 'Yetkazildi (offline saqlandi)'
            : 'Qaytdi (offline saqlandi)'),
        backgroundColor: Colors.orange,
      ));
      Navigator.pop(context, true);
      return;
    }

    // O'zgargan itemlarni JSON sifatida yuborish
    String? itemsJson;
    final items = List<Map<String, dynamic>>.from(_d['items'] ?? []);
    if (items.isNotEmpty) {
      itemsJson = jsonEncode(items);
    }

    final result = await ApiService.updateDeliveryStatus(token, _d['id'], newStatus, latitude: lat, longitude: lng, notes: notes, items: itemsJson, naqdAmount: naqd > 0 ? naqd : null, plastikAmount: plastik > 0 ? plastik : null);
    if (!mounted) return;
    setState(() => _isBusy = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(newStatus == 'delivered' ? 'Yetkazildi!' : 'Qaytdi'), backgroundColor: Colors.green));
      Navigator.pop(context, true);
    } else {
      final err = result['error']?.toString() ?? 'Xato';
      if (err.contains('TimeoutException') || err.contains('Ulanish xatosi')) {
        // Timeout — offline ga saqlash
        await _offlineDb.saveOfflineDeliveryAction(
          deliveryId: _d['id'] as int,
          partnerName: (_d['partner_name'] ?? '').toString(),
          newStatus: newStatus,
          latitude: lat,
          longitude: lng,
          notes: notes,
        );
        await _offlineDb.updateCachedDeliveryStatus(_d['id'] as int, newStatus);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Server javob bermadi. Offline saqlandi — internet qaytganda sinxronlanadi.'),
          backgroundColor: Colors.orange,
        ));
        Navigator.pop(context, true);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err), backgroundColor: Colors.red));
      }
    }
  }

  void _showDeliverDialog() {
    final naqdController = TextEditingController();
    final plastikController = TextEditingController();
    final total = (_d['total'] ?? 0).toDouble();
    final syncService = SyncService();

    showDialog(context: context, builder: (ctx) {
      return StatefulBuilder(builder: (ctx, setDialogState) {
        final naqd = double.tryParse(naqdController.text) ?? 0;
        final plastik = double.tryParse(plastikController.text) ?? 0;
        final qarz = (total - naqd - plastik).clamp(0, total);

        return AlertDialog(
          title: Row(children: [
            const Expanded(child: Text('Yetkazishni tasdiqlash', style: TextStyle(fontSize: 16))),
            if (!syncService.isOnline)
              const Icon(Icons.wifi_off, size: 18, color: Colors.orange),
          ]),
          content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (!syncService.isOnline)
              Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: Colors.orange.shade50, borderRadius: BorderRadius.circular(8)),
                child: const Text('Offline rejimda saqlanadi', style: TextStyle(color: Colors.orange, fontSize: 12)),
              ),
            Text('Jami: ${_fmt(total)} so\'m', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            // Naqd
            TextField(
              controller: naqdController,
              keyboardType: TextInputType.number,
              onChanged: (_) => setDialogState(() {}),
              decoration: InputDecoration(
                labelText: 'Naqd',
                hintText: '0',
                suffixText: 'so\'m',
                prefixIcon: const Icon(Icons.money, color: Colors.green, size: 20),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 10),
            // Plastik
            TextField(
              controller: plastikController,
              keyboardType: TextInputType.number,
              onChanged: (_) => setDialogState(() {}),
              decoration: InputDecoration(
                labelText: 'Plastik',
                hintText: '0',
                suffixText: 'so\'m',
                prefixIcon: const Icon(Icons.credit_card, color: Colors.blue, size: 20),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              ),
            ),
            const SizedBox(height: 10),
            // Qarz ko'rsatish
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: qarz > 0 ? Colors.red.shade50 : Colors.green.shade50,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(children: [
                Icon(qarz > 0 ? Icons.warning_amber : Icons.check_circle, color: qarz > 0 ? Colors.red : Colors.green, size: 20),
                const SizedBox(width: 8),
                Text('Qarz: ', style: TextStyle(color: qarz > 0 ? Colors.red : Colors.green)),
                Text(_fmt(qarz) + ' so\'m', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: qarz > 0 ? Colors.red : Colors.green)),
              ]),
            ),
            const SizedBox(height: 8),
            // Tez tugmalar
            Wrap(spacing: 8, children: [
              ActionChip(label: Text('Naqd ${_fmt(total)}'), onPressed: () {
                naqdController.text = total.toInt().toString();
                plastikController.text = '';
                setDialogState(() {});
              }),
              ActionChip(label: Text('Plastik ${_fmt(total)}'), onPressed: () {
                naqdController.text = '';
                plastikController.text = total.toInt().toString();
                setDialogState(() {});
              }),
              ActionChip(label: const Text('Qarz'), onPressed: () {
                naqdController.text = '';
                plastikController.text = '';
                setDialogState(() {});
              }),
            ]),
          ])),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Bekor')),
            ElevatedButton.icon(
              icon: const Icon(Icons.check_circle, size: 18),
              label: const Text('Yetkazildi'),
              style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white),
              onPressed: () {
                Navigator.pop(ctx);
                _doAction('delivered', naqdAmount: naqd, plastikAmount: plastik);
              },
            ),
          ],
        );
      });
    });
  }

  void _showRejectDialog() {
    showDialog(context: context, builder: (ctx) => AlertDialog(
      title: const Text('Qaytarish'),
      content: const Text('Yetkazishni qaytarasizmi?'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Bekor')),
        ElevatedButton(
          onPressed: () { Navigator.pop(ctx); _doAction('failed'); },
          style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
          child: const Text('Qaytdi'),
        ),
      ],
    ));
  }

  @override
  Widget build(BuildContext context) {
    final items = List<Map<String, dynamic>>.from(_d['items'] ?? []);
    final status = _d['status'] ?? 'pending';
    final isActive = !['delivered', 'failed'].contains(status);
    final hasGps = _d['latitude'] != null && _d['longitude'] != null;

    return Scaffold(
      appBar: AppBar(
        title: Text(_d['partner_name'] ?? 'Yetkazish', style: const TextStyle(fontSize: 16)),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // Buyurtma raqami
          Row(children: [
            Expanded(child: Text(_d['order_number'] ?? _d['number'] ?? '', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold))),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: (isActive ? Colors.blue : status == 'delivered' ? Colors.green : Colors.red).withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(isActive ? 'Yo\'lda' : status == 'delivered' ? 'Yetkazildi' : 'Qaytdi',
                style: TextStyle(color: isActive ? Colors.blue : status == 'delivered' ? Colors.green : Colors.red, fontWeight: FontWeight.w600)),
            ),
          ]),
          const SizedBox(height: 16),

          // Mijoz info
          _section('Mijoz', [
            _row(Icons.person, _d['partner_name'] ?? ''),
            if ((_d['partner_address'] ?? _d['delivery_address'] ?? '').toString().isNotEmpty)
              _row(Icons.location_on, _d['partner_address'] ?? _d['delivery_address'], color: Colors.red),
            if ((_d['landmark'] ?? '').toString().isNotEmpty)
              _row(Icons.near_me, 'Mo\'ljal: ${_d['landmark']}', color: Colors.orange),
            if (hasGps) _gpsButton(),
            if ((_d['partner_phone'] ?? '').toString().isNotEmpty)
              _phoneButton(_d['partner_phone']),
            if ((_d['partner_phone2'] ?? '').toString().isNotEmpty)
              _phoneButton(_d['partner_phone2']),
          ]),
          const SizedBox(height: 12),

          // Buyurtma tarkibi
          _section('Buyurtma tarkibi', [
            if (items.isEmpty)
              const Text('Ma\'lumot yo\'q', style: TextStyle(color: Colors.grey))
            else ...[
              ...items.asMap().entries.map((entry) {
                final idx = entry.key;
                final item = entry.value;
                final qty = (item['quantity'] ?? 0).toDouble();
                final price = (item['price'] ?? 0).toDouble();
                return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(children: [
                  Expanded(child: Text(item['name'] ?? '', style: const TextStyle(fontSize: 14))),
                  if (isActive)
                    GestureDetector(
                      onTap: () => _editItemQty(idx, item['name'] ?? '', qty),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(color: Colors.blue.shade50, border: Border.all(color: Colors.blue.shade200), borderRadius: BorderRadius.circular(6)),
                        child: Text('x${qty.toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600, color: Colors.blue)),
                      ),
                    )
                  else
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(6)),
                      child: Text('x${qty.toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    ),
                  const SizedBox(width: 8),
                  SizedBox(width: 80, child: Text(_fmt(qty * price), textAlign: TextAlign.right, style: const TextStyle(fontSize: 13))),
                ]),
              ); }),
              const Divider(height: 16),
              Row(children: [
                const Expanded(child: Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                Text('${_fmt(_calcTotal())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
              ]),
            ],
          ]),

          if ((_d['notes'] ?? '').toString().isNotEmpty) ...[
            const SizedBox(height: 12),
            _section('Izoh', [Text(_d['notes'], style: TextStyle(color: Colors.grey[700]))]),
          ],

          // To'lov ma'lumoti (yetkazilgan buyurtmalar uchun)
          if (!isActive) ...[
            const SizedBox(height: 12),
            _section('To\'lov', [
              Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                const Text('Jami:'),
                Text('${_fmt(_calcTotal())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold)),
              ]),
              if ((_d['paid'] ?? 0).toDouble() > 0) ...[
                const SizedBox(height: 4),
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  const Text('To\'langan:', style: TextStyle(color: Colors.green)),
                  Text('${_fmt((_d['paid'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.green)),
                ]),
              ],
              if ((_d['debt'] ?? 0).toDouble() > 0) ...[
                const SizedBox(height: 4),
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  const Text('Qarz:', style: TextStyle(color: Colors.red)),
                  Text('${_fmt((_d['debt'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.red)),
                ]),
              ],
              if ((_d['paid'] ?? 0).toDouble() > 0 && (_d['debt'] ?? 0).toDouble() <= 0) ...[
                const SizedBox(height: 4),
                Row(children: [
                  const Icon(Icons.check_circle, color: Colors.green, size: 16),
                  const SizedBox(width: 4),
                  const Text('To\'liq to\'langan', style: TextStyle(color: Colors.green, fontWeight: FontWeight.w500)),
                ]),
              ],
            ]),
          ],

          const SizedBox(height: 24),

          // Amallar
          if (isActive && !_isBusy) ...[
            SizedBox(width: double.infinity, height: 50, child: ElevatedButton.icon(
              icon: const Icon(Icons.check_circle, size: 22),
              label: const Text('Yetkazildi', style: TextStyle(fontSize: 16)),
              style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
              onPressed: _showDeliverDialog,
            )),
            const SizedBox(height: 10),
            SizedBox(width: double.infinity, height: 44, child: OutlinedButton.icon(
              icon: const Icon(Icons.cancel, size: 20),
              label: const Text('Qaytdi'),
              style: OutlinedButton.styleFrom(foregroundColor: Colors.red, side: const BorderSide(color: Colors.red), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
              onPressed: _showRejectDialog,
            )),
          ],
          if (_isBusy)
            const Center(child: Padding(padding: EdgeInsets.all(20), child: CircularProgressIndicator())),
        ]),
      ),
    );
  }

  Widget _section(String title, List<Widget> children) {
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.black54)),
        const SizedBox(height: 8),
        ...children,
      ])),
    );
  }

  Widget _row(IconData icon, String text, {Color color = Colors.black87}) {
    return Padding(padding: const EdgeInsets.only(bottom: 4), child: Row(children: [
      Icon(icon, size: 16, color: color), const SizedBox(width: 8),
      Expanded(child: Text(text, style: TextStyle(fontSize: 14, color: color))),
    ]));
  }

  Widget _gpsButton() {
    final lat = _d['latitude'];
    final lng = _d['longitude'];
    return Padding(padding: const EdgeInsets.only(bottom: 4, top: 4), child: Row(children: [
      // Xaritada ochish
      Expanded(child: GestureDetector(
        onTap: () async {
          final name = Uri.encodeComponent(_d['partner_name'] ?? '');
          // Avval geo: intent (tizim xarita ilovasini ochadi)
          final geo = Uri.parse('geo:$lat,$lng?q=$lat,$lng($name)');
          try {
            final launched = await launchUrl(geo);
            if (launched) return;
          } catch (_) {}
          // Fallback: brauzerda Yandex Maps ochish
          final webUrl = Uri.parse('https://yandex.ru/maps/?pt=$lng,$lat&z=16&l=map');
          await launchUrl(webUrl, mode: LaunchMode.externalApplication);
        },
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(color: Colors.green.shade50, borderRadius: BorderRadius.circular(10)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.navigation, size: 18, color: Colors.green),
            const SizedBox(width: 6),
            Text('$lat, $lng', style: const TextStyle(color: Colors.green, fontSize: 13, fontWeight: FontWeight.w500)),
            const SizedBox(width: 6),
            const Icon(Icons.open_in_new, size: 14, color: Colors.green),
          ]),
        ),
      )),
      const SizedBox(width: 8),
      // Nusxalash
      GestureDetector(
        onTap: () {
          Clipboard.setData(ClipboardData(text: '$lat, $lng'));
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Nusxalandi')));
        },
        child: Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(10)),
          child: const Icon(Icons.copy, size: 16, color: Colors.grey),
        ),
      ),
    ]));
  }

  Widget _phoneButton(String phone) {
    return Padding(padding: const EdgeInsets.only(bottom: 4), child: Row(children: [
      // Qo'ng'iroq qilish
      Expanded(child: GestureDetector(
        onTap: () => launchUrl(Uri.parse('tel:$phone')),
        child: Row(children: [
          const Icon(Icons.phone, size: 16, color: Colors.green), const SizedBox(width: 8),
          Text(phone, style: const TextStyle(fontSize: 14, color: Colors.green, fontWeight: FontWeight.w500, decoration: TextDecoration.underline)),
        ]),
      )),
      const SizedBox(width: 8),
      // Nusxalash
      GestureDetector(
        onTap: () {
          Clipboard.setData(ClipboardData(text: phone));
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$phone nusxalandi')));
        },
        child: const Icon(Icons.copy, size: 14, color: Colors.grey),
      ),
    ]));
  }
}
