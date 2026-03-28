import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';

class DeliveriesScreen extends StatefulWidget {
  const DeliveriesScreen({super.key});

  @override
  State<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends State<DeliveriesScreen> {
  final SessionService _session = SessionService();
  List<Map<String, dynamic>> _deliveries = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadDeliveries();
  }

  Future<void> _loadDeliveries() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;
    final result = await ApiService.getDeliveries(token);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (result['success'] == true) {
          _deliveries = List<Map<String, dynamic>>.from(result['deliveries'] ?? []);
        }
      });
    }
  }

  Future<void> _updateStatus(Map<String, dynamic> d, String newStatus) async {
    final label = _statusLabel(newStatus);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(label),
        content: Text('${d['partner_name'] ?? d['order_number']} — $label?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Bekor')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: _statusColor(newStatus), foregroundColor: Colors.white),
            child: const Text('Ha'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final token = await _session.getToken();
    if (token == null) return;
    double? lat, lng;
    try {
      final pos = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high, timeLimit: const Duration(seconds: 10));
      lat = pos.latitude;
      lng = pos.longitude;
    } catch (_) {}
    final result = await ApiService.updateDeliveryStatus(token, d['id'], newStatus, latitude: lat, longitude: lng);
    if (!mounted) return;
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(label), backgroundColor: Colors.green));
      _loadDeliveries();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  String _statusLabel(String s) {
    switch (s) { case 'pending': return 'Kutilmoqda'; case 'in_progress': return 'Yo\'lda'; case 'delivered': return 'Yetkazildi'; case 'failed': return 'Qaytdi'; default: return s; }
  }
  Color _statusColor(String s) {
    switch (s) { case 'pending': return Colors.orange; case 'in_progress': return Colors.blue; case 'delivered': return Colors.green; case 'failed': return Colors.red; default: return Colors.grey; }
  }
  IconData _statusIcon(String s) {
    switch (s) { case 'pending': return Icons.pending_actions; case 'in_progress': return Icons.local_shipping; case 'delivered': return Icons.check_circle; case 'failed': return Icons.cancel; default: return Icons.help; }
  }
  String _fmt(double v) {
    if (v <= 0) return '0';
    final s = v.toInt().toString();
    final b = StringBuffer();
    for (int i = 0; i < s.length; i++) { if (i > 0 && (s.length - i) % 3 == 0) b.write(' '); b.write(s[i]); }
    return b.toString();
  }

  @override
  Widget build(BuildContext context) {
    final active = _deliveries.where((d) => d['status'] == 'in_progress' || d['status'] == 'pending').toList();
    final done = _deliveries.where((d) => d['status'] == 'delivered' || d['status'] == 'failed').toList();
    return _isLoading
        ? const Center(child: CircularProgressIndicator())
        : _deliveries.isEmpty
            ? Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(Icons.local_shipping_outlined, size: 64, color: Colors.grey[400]),
                const SizedBox(height: 16),
                const Text('Yetkazishlar yo\'q', style: TextStyle(color: Colors.grey)),
              ]))
            : RefreshIndicator(
                onRefresh: _loadDeliveries,
                child: ListView(
                  children: [
                    if (active.isNotEmpty) ...[
                      Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                        child: Text('Faol yetkazishlar (${active.length})', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold))),
                      ...active.map((d) => _card(d)),
                    ],
                    if (done.isNotEmpty) ...[
                      Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                        child: Text('Yakunlangan (${done.length})', style: TextStyle(fontSize: 13, color: Colors.grey[600]))),
                      ...done.map((d) => _card(d)),
                    ],
                    const SizedBox(height: 20),
                  ],
                ),
              );
  }

  Widget _card(Map<String, dynamic> d) {
    final status = d['status'] ?? 'pending';
    final color = _statusColor(status);
    final isActive = status == 'in_progress' || status == 'pending';
    final items = List<Map<String, dynamic>>.from(d['items'] ?? []);
    final hasGps = d['latitude'] != null && d['longitude'] != null;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: isActive ? BorderSide(color: color.withOpacity(0.4), width: 1.5) : BorderSide.none,
      ),
      elevation: isActive ? 3 : 1,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // Sarlavha
          Row(children: [
            Icon(_statusIcon(status), color: color, size: 24),
            const SizedBox(width: 10),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(d['order_number'] ?? d['number'] ?? '', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
              if ((d['partner_name'] ?? '').isNotEmpty)
                Text(d['partner_name'], style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
            ])),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: color.withOpacity(0.12), borderRadius: BorderRadius.circular(12)),
              child: Text(_statusLabel(status), style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
            ),
          ]),

          const Divider(height: 16),

          // ===== MANZIL VA LOKATSIYA =====
          if ((d['partner_address'] ?? d['delivery_address'] ?? '').toString().isNotEmpty)
            _infoRow(Icons.location_on, Colors.red, d['partner_address'] ?? d['delivery_address'] ?? ''),
          if ((d['landmark'] ?? '').toString().isNotEmpty)
            _infoRow(Icons.near_me, Colors.orange, 'Mo\'ljal: ${d['landmark']}'),

          // GPS tugma
          if (hasGps)
            Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 4),
              child: GestureDetector(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: '${d['latitude']}, ${d['longitude']}'));
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Koordinatalar nusxalandi — Yandex/Google Maps da oching')));
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(color: Colors.blue.shade50, borderRadius: BorderRadius.circular(8)),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.navigation, size: 16, color: Colors.blue),
                    const SizedBox(width: 4),
                    Text('${d['latitude']}, ${d['longitude']}', style: const TextStyle(fontSize: 12, color: Colors.blue)),
                    const SizedBox(width: 4),
                    const Icon(Icons.copy, size: 14, color: Colors.blue),
                  ]),
                ),
              ),
            ),

          // ===== TELEFON =====
          if ((d['partner_phone'] ?? '').toString().isNotEmpty)
            _phoneRow(d['partner_phone']),
          if ((d['partner_phone2'] ?? '').toString().isNotEmpty)
            _phoneRow(d['partner_phone2']),

          // ===== BUYURTMA TARKIBI =====
          if (items.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: Colors.grey.shade50, borderRadius: BorderRadius.circular(8)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Buyurtma tarkibi:', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.black54)),
                const SizedBox(height: 4),
                ...items.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Row(children: [
                    Expanded(child: Text(item['name'] ?? '', style: const TextStyle(fontSize: 13))),
                    Text('x${(item['quantity'] ?? 0).toDouble().toStringAsFixed(0)}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                    const SizedBox(width: 8),
                    SizedBox(width: 70, child: Text('${_fmt((item['total'] ?? 0).toDouble())}', textAlign: TextAlign.right, style: const TextStyle(fontSize: 12, color: Colors.grey))),
                  ]),
                )),
                const Divider(height: 8),
                Row(children: [
                  const Expanded(child: Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold))),
                  Text('${_fmt((d['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                ]),
              ]),
            ),
          ] else if ((d['total'] ?? 0) > 0) ...[
            const SizedBox(height: 6),
            Text('${_fmt((d['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          ],

          // ===== IZOH =====
          if ((d['notes'] ?? '').toString().isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(d['notes'], style: TextStyle(fontSize: 12, color: Colors.grey[600], fontStyle: FontStyle.italic)),
          ],

          // ===== AMALLAR =====
          if (isActive) ...[
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: ElevatedButton.icon(
                icon: const Icon(Icons.check_circle, size: 18),
                label: const Text('Yetkazildi'),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(vertical: 10)),
                onPressed: () => _updateStatus(d, 'delivered'),
              )),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton.icon(
                icon: const Icon(Icons.cancel, size: 18),
                label: const Text('Qaytdi'),
                style: OutlinedButton.styleFrom(foregroundColor: Colors.red, side: const BorderSide(color: Colors.red), padding: const EdgeInsets.symmetric(vertical: 10)),
                onPressed: () => _updateStatus(d, 'failed'),
              )),
            ]),
          ],
        ]),
      ),
    );
  }

  Widget _infoRow(IconData icon, Color iconColor, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(children: [
        Icon(icon, size: 16, color: iconColor),
        const SizedBox(width: 6),
        Expanded(child: Text(text, style: const TextStyle(fontSize: 13))),
      ]),
    );
  }

  Widget _phoneRow(String phone) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: GestureDetector(
        onTap: () {
          Clipboard.setData(ClipboardData(text: phone));
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$phone nusxalandi')));
        },
        child: Row(children: [
          const Icon(Icons.phone, size: 16, color: Colors.green),
          const SizedBox(width: 6),
          Text(phone, style: const TextStyle(fontSize: 14, color: Colors.green, fontWeight: FontWeight.w500, decoration: TextDecoration.underline)),
          const SizedBox(width: 4),
          const Icon(Icons.copy, size: 12, color: Colors.green),
        ]),
      ),
    );
  }
}
