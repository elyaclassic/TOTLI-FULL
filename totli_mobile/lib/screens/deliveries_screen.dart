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

  Future<void> _updateStatus(Map<String, dynamic> delivery, String newStatus) async {
    final label = _statusLabel(newStatus);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(label),
        content: Text('${delivery['partner_name'] ?? delivery['order_number']} — $label?'),
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
    if (confirmed != true) return;

    final token = await _session.getToken();
    if (token == null) return;

    double? lat, lng;
    try {
      final pos = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high, timeLimit: const Duration(seconds: 10));
      lat = pos.latitude;
      lng = pos.longitude;
    } catch (_) {}

    final result = await ApiService.updateDeliveryStatus(token, delivery['id'], newStatus, latitude: lat, longitude: lng);
    if (!mounted) return;
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(label), backgroundColor: Colors.green));
      _loadDeliveries();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  String _statusLabel(String s) {
    switch (s) {
      case 'pending': return 'Kutilmoqda';
      case 'in_progress': return 'Yo\'lda';
      case 'delivered': return 'Yetkazildi';
      case 'failed': return 'Bekor / Qaytdi';
      default: return s;
    }
  }

  Color _statusColor(String s) {
    switch (s) {
      case 'pending': return Colors.orange;
      case 'in_progress': return Colors.blue;
      case 'delivered': return Colors.green;
      case 'failed': return Colors.red;
      default: return Colors.grey;
    }
  }

  IconData _statusIcon(String s) {
    switch (s) {
      case 'pending': return Icons.pending_actions;
      case 'in_progress': return Icons.local_shipping;
      case 'delivered': return Icons.check_circle;
      case 'failed': return Icons.cancel;
      default: return Icons.help;
    }
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

  @override
  Widget build(BuildContext context) {
    // Faol va yakunlangan
    final active = _deliveries.where((d) => d['status'] == 'in_progress' || d['status'] == 'pending').toList();
    final done = _deliveries.where((d) => d['status'] == 'delivered' || d['status'] == 'failed').toList();
    return _isLoading
        ? const Center(child: CircularProgressIndicator())
        : _deliveries.isEmpty
            ? Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.local_shipping_outlined, size: 64, color: Colors.grey[400]),
                    const SizedBox(height: 16),
                    const Text('Yetkazishlar yo\'q', style: TextStyle(color: Colors.grey)),
                  ],
                ),
              )
            : RefreshIndicator(
                onRefresh: _loadDeliveries,
                child: ListView(
                  children: [
                    if (active.isNotEmpty) ...[
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                        child: Text('Faol yetkazishlar (${active.length})', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
                      ),
                      ...active.map((d) => _buildDeliveryCard(d)),
                    ],
                    if (done.isNotEmpty) ...[
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                        child: Text('Yakunlangan (${done.length})', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: Colors.grey[600])),
                      ),
                      ...done.map((d) => _buildDeliveryCard(d)),
                    ],
                    const SizedBox(height: 20),
                  ],
                ),
              );
  }

  Widget _buildDeliveryCard(Map<String, dynamic> d) {
    final status = d['status'] ?? 'pending';
    final color = _statusColor(status);
    final isActive = status == 'in_progress' || status == 'pending';
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: isActive ? BorderSide(color: color.withOpacity(0.4), width: 1.5) : BorderSide.none,
      ),
      elevation: isActive ? 3 : 1,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Sarlavha
            Row(
              children: [
                Icon(_statusIcon(status), color: color, size: 24),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(d['order_number'] ?? d['number'] ?? '#${d['id']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                      if ((d['partner_name'] ?? '').isNotEmpty)
                        Text(d['partner_name'], style: const TextStyle(fontSize: 13)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: color.withOpacity(0.12), borderRadius: BorderRadius.circular(12)),
                  child: Text(_statusLabel(status), style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
                ),
              ],
            ),
            const SizedBox(height: 10),

            // Manzil
            if ((d['delivery_address'] ?? '').toString().isNotEmpty)
              Row(
                children: [
                  const Icon(Icons.location_on, size: 15, color: Colors.grey),
                  const SizedBox(width: 4),
                  Expanded(child: Text(d['delivery_address'], style: const TextStyle(fontSize: 13))),
                  if (d['latitude'] != null && d['longitude'] != null)
                    GestureDetector(
                      onTap: () {
                        Clipboard.setData(ClipboardData(text: '${d['latitude']}, ${d['longitude']}'));
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Koordinatalar nusxalandi')));
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(color: Colors.blue.shade50, borderRadius: BorderRadius.circular(8)),
                        child: const Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [Icon(Icons.navigation, size: 14, color: Colors.blue), SizedBox(width: 3), Text('Xarita', style: TextStyle(fontSize: 11, color: Colors.blue))],
                        ),
                      ),
                    ),
                ],
              ),

            // Telefon
            if ((d['partner_phone'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 4),
              GestureDetector(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: d['partner_phone']));
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${d['partner_phone']} nusxalandi')));
                },
                child: Row(
                  children: [
                    const Icon(Icons.phone, size: 15, color: Colors.green),
                    const SizedBox(width: 4),
                    Text(d['partner_phone'], style: const TextStyle(fontSize: 13, color: Colors.green, decoration: TextDecoration.underline)),
                  ],
                ),
              ),
            ],

            // Izoh
            if ((d['notes'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(d['notes'], style: TextStyle(fontSize: 12, color: Colors.grey[600], fontStyle: FontStyle.italic)),
            ],

            // Summa
            if ((d['total'] ?? 0) > 0) ...[
              const SizedBox(height: 6),
              Text('${_formatMoney((d['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            ],

            // Amallar
            if (isActive) ...[
              const Divider(height: 20),
              Row(
                children: [
                  // Yetkazildi
                  Expanded(
                    child: ElevatedButton.icon(
                      icon: const Icon(Icons.check_circle, size: 18),
                      label: const Text('Yetkazildi'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.green,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 10),
                      ),
                      onPressed: () => _updateStatus(d, 'delivered'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  // Bekor / Qaytdi
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.cancel, size: 18),
                      label: const Text('Qaytdi'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.red,
                        side: const BorderSide(color: Colors.red),
                        padding: const EdgeInsets.symmetric(vertical: 10),
                      ),
                      onPressed: () => _updateStatus(d, 'failed'),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
