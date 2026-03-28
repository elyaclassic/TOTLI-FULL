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
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_statusLabel(newStatus)),
        content: Text('${delivery['partner_name'] ?? delivery['order_number']} uchun holatni o\'zgartirmoqchimisiz?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Bekor')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(backgroundColor: _statusColor(newStatus)),
            child: const Text('Ha', style: TextStyle(color: Colors.white)),
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
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_statusLabel(newStatus)), backgroundColor: Colors.green));
      _loadDeliveries();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  String _statusLabel(String s) {
    switch (s) {
      case 'pending': return 'Kutilmoqda';
      case 'picked_up': return 'Olib ketildi';
      case 'in_progress': return 'Yo\'lda';
      case 'delivered': return 'Yetkazildi';
      case 'failed': return 'Muvaffaqiyatsiz';
      default: return s;
    }
  }

  Color _statusColor(String s) {
    switch (s) {
      case 'pending': return Colors.orange;
      case 'picked_up': return Colors.blue;
      case 'in_progress': return Colors.indigo;
      case 'delivered': return Colors.green;
      case 'failed': return Colors.red;
      default: return Colors.grey;
    }
  }

  IconData _statusIcon(String s) {
    switch (s) {
      case 'pending': return Icons.pending_actions;
      case 'picked_up': return Icons.inventory;
      case 'in_progress': return Icons.local_shipping;
      case 'delivered': return Icons.check_circle;
      case 'failed': return Icons.cancel;
      default: return Icons.help;
    }
  }

  void _openMap(dynamic lat, dynamic lng) async {
    final uri = Uri.parse('geo:$lat,$lng?q=$lat,$lng');
    try {
      await Clipboard.setData(ClipboardData(text: '$lat, $lng'));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Koordinatalar nusxalandi. Xaritada oching.')),
        );
      }
    } catch (_) {}
  }

  void _callPhone(String phone) async {
    try {
      await Clipboard.setData(ClipboardData(text: phone));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$phone nusxalandi')),
        );
      }
    } catch (_) {}
  }

  String _formatMoney(double v) {
    if (v <= 0) return '0';
    final intVal = v.toInt();
    final str = intVal.toString();
    final buf = StringBuffer();
    for (int i = 0; i < str.length; i++) {
      if (i > 0 && (str.length - i) % 3 == 0) buf.write(' ');
      buf.write(str[i]);
    }
    return buf.toString();
  }

  List<String> _nextStatuses(String current) {
    switch (current) {
      case 'pending': return ['picked_up', 'failed'];
      case 'picked_up': return ['in_progress', 'failed'];
      case 'in_progress': return ['delivered', 'failed'];
      default: return [];
    }
  }

  @override
  Widget build(BuildContext context) {
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
                child: ListView.builder(
                  itemCount: _deliveries.length,
                  itemBuilder: (ctx, i) => _buildDeliveryTile(_deliveries[i]),
                ),
              );
  }

  Widget _buildDeliveryTile(Map<String, dynamic> d) {
    final status = d['status'] ?? 'pending';
    final color = _statusColor(status);
    final nextActions = _nextStatuses(status);
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(_statusIcon(status), color: color, size: 24),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(d['number'] ?? d['order_number'] ?? '#${d['id']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                      if (d['partner_name'] != null) Text(d['partner_name'], style: const TextStyle(fontSize: 13)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: color.withOpacity(0.15), borderRadius: BorderRadius.circular(12)),
                  child: Text(_statusLabel(status), style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
                ),
              ],
            ),
            if ((d['delivery_address'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.location_on, size: 14, color: Colors.grey),
                  const SizedBox(width: 4),
                  Expanded(child: Text(d['delivery_address'], style: const TextStyle(fontSize: 12, color: Colors.grey))),
                  if (d['latitude'] != null && d['longitude'] != null)
                    GestureDetector(
                      onTap: () => _openMap(d['latitude'], d['longitude']),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(color: Colors.blue.shade50, borderRadius: BorderRadius.circular(8)),
                        child: const Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.navigation, size: 14, color: Colors.blue),
                            SizedBox(width: 2),
                            Text('Xarita', style: TextStyle(fontSize: 11, color: Colors.blue)),
                          ],
                        ),
                      ),
                    ),
                ],
              ),
            ],
            if ((d['partner_phone'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 4),
              GestureDetector(
                onTap: () => _callPhone(d['partner_phone']),
                child: Row(
                  children: [
                    const Icon(Icons.phone, size: 14, color: Colors.green),
                    const SizedBox(width: 4),
                    Text(d['partner_phone'], style: const TextStyle(fontSize: 12, color: Colors.green, decoration: TextDecoration.underline)),
                  ],
                ),
              ),
            ],
            if ((d['notes'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(d['notes'], style: TextStyle(fontSize: 11, color: Colors.grey[600], fontStyle: FontStyle.italic)),
            ],
            if (d['total'] != null && (d['total'] ?? 0) > 0) ...[
              const SizedBox(height: 4),
              Text('${_formatMoney((d['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.w600)),
            ],
            if (nextActions.isNotEmpty) ...[
              const SizedBox(height: 10),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: nextActions.map((ns) => Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: ElevatedButton.icon(
                    icon: Icon(_statusIcon(ns), size: 16),
                    label: Text(_statusLabel(ns), style: const TextStyle(fontSize: 12)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _statusColor(ns),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      minimumSize: Size.zero,
                    ),
                    onPressed: () => _updateStatus(d, ns),
                  ),
                )).toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
