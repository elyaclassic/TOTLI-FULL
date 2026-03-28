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
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;
    final r = await ApiService.getDeliveries(token);
    if (mounted) setState(() { _isLoading = false; if (r['success'] == true) _deliveries = List<Map<String, dynamic>>.from(r['deliveries'] ?? []); });
  }

  String _sLabel(String s) { switch (s) { case 'in_progress': return 'Yo\'lda'; case 'delivered': return 'Yetkazildi'; case 'failed': return 'Qaytdi'; default: return 'Kutilmoqda'; } }
  Color _sColor(String s) { switch (s) { case 'in_progress': return Colors.blue; case 'delivered': return Colors.green; case 'failed': return Colors.red; default: return Colors.orange; } }
  String _fmt(double v) { if (v <= 0) return '0'; final s = v.toInt().toString(); final b = StringBuffer(); for (int i = 0; i < s.length; i++) { if (i > 0 && (s.length - i) % 3 == 0) b.write(' '); b.write(s[i]); } return b.toString(); }

  @override
  Widget build(BuildContext context) {
    final active = _deliveries.where((d) => d['status'] == 'in_progress' || d['status'] == 'pending').toList();
    final done = _deliveries.where((d) => d['status'] == 'delivered' || d['status'] == 'failed').toList();
    return _isLoading
        ? const Center(child: CircularProgressIndicator())
        : _deliveries.isEmpty
            ? Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(Icons.local_shipping_outlined, size: 64, color: Colors.grey[400]), const SizedBox(height: 16),
                const Text('Yetkazishlar yo\'q', style: TextStyle(color: Colors.grey))]))
            : RefreshIndicator(onRefresh: _load, child: ListView(children: [
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
    final isActive = status == 'in_progress' || status == 'pending';
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
  late Map<String, dynamic> _d;
  bool _isBusy = false;

  @override
  void initState() { super.initState(); _d = Map<String, dynamic>.from(widget.delivery); }

  String _fmt(double v) { if (v <= 0) return '0'; final s = v.toInt().toString(); final b = StringBuffer(); for (int i = 0; i < s.length; i++) { if (i > 0 && (s.length - i) % 3 == 0) b.write(' '); b.write(s[i]); } return b.toString(); }

  Future<void> _doAction(String newStatus, {double? paidAmount}) async {
    setState(() => _isBusy = true);
    final token = await _session.getToken();
    if (token == null) return;
    double? lat, lng;
    try {
      final pos = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high, timeLimit: const Duration(seconds: 10));
      lat = pos.latitude; lng = pos.longitude;
    } catch (_) {}
    final notes = paidAmount != null && paidAmount > 0 ? 'To\'lov: ${paidAmount.toInt()} so\'m' : null;
    final result = await ApiService.updateDeliveryStatus(token, _d['id'], newStatus, latitude: lat, longitude: lng, notes: notes);
    if (!mounted) return;
    setState(() => _isBusy = false);
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(newStatus == 'delivered' ? 'Yetkazildi!' : 'Qaytdi'), backgroundColor: Colors.green));
      Navigator.pop(context, true);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  void _showDeliverDialog() {
    final payController = TextEditingController();
    final total = (_d['total'] ?? 0).toDouble();
    showDialog(context: context, builder: (ctx) => AlertDialog(
      title: const Text('Yetkazishni tasdiqlash'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        Text('Jami: ${_fmt(total)} so\'m', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        const SizedBox(height: 16),
        TextField(
          controller: payController,
          keyboardType: TextInputType.number,
          decoration: InputDecoration(
            labelText: 'Olingan to\'lov summasi',
            hintText: '0',
            suffixText: 'so\'m',
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
          ),
        ),
        const SizedBox(height: 8),
        // Tez tugmalar
        Wrap(spacing: 8, children: [
          ActionChip(label: Text('${_fmt(total)}'), onPressed: () => payController.text = total.toInt().toString()),
          ActionChip(label: const Text('0 (qarz)'), onPressed: () => payController.text = '0'),
        ]),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Bekor')),
        ElevatedButton.icon(
          icon: const Icon(Icons.check_circle, size: 18),
          label: const Text('Yetkazildi'),
          style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white),
          onPressed: () {
            Navigator.pop(ctx);
            final paid = double.tryParse(payController.text) ?? 0;
            _doAction('delivered', paidAmount: paid);
          },
        ),
      ],
    ));
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
    final isActive = status == 'in_progress' || status == 'pending';
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
              ...items.map((item) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(children: [
                  Expanded(child: Text(item['name'] ?? '', style: const TextStyle(fontSize: 14))),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(6)),
                    child: Text('x${(item['quantity'] ?? 0).toDouble().toStringAsFixed(0)}', style: const TextStyle(fontWeight: FontWeight.w600)),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(width: 80, child: Text('${_fmt((item['total'] ?? 0).toDouble())}', textAlign: TextAlign.right, style: const TextStyle(fontSize: 13))),
                ]),
              )),
              const Divider(height: 16),
              Row(children: [
                const Expanded(child: Text('Jami:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                Text('${_fmt((_d['total'] ?? 0).toDouble())} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
              ]),
            ],
          ]),

          if ((_d['notes'] ?? '').toString().isNotEmpty) ...[
            const SizedBox(height: 12),
            _section('Izoh', [Text(_d['notes'], style: TextStyle(color: Colors.grey[700]))]),
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
    return Padding(padding: const EdgeInsets.only(bottom: 4, top: 4), child: GestureDetector(
      onTap: () {
        Clipboard.setData(ClipboardData(text: '${_d['latitude']}, ${_d['longitude']}'));
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Koordinatalar nusxalandi')));
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(color: Colors.blue.shade50, borderRadius: BorderRadius.circular(10)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.navigation, size: 18, color: Colors.blue),
          const SizedBox(width: 6),
          Text('${_d['latitude']}, ${_d['longitude']}', style: const TextStyle(color: Colors.blue, fontSize: 13)),
          const SizedBox(width: 6),
          const Icon(Icons.copy, size: 14, color: Colors.blue),
        ]),
      ),
    ));
  }

  Widget _phoneButton(String phone) {
    return Padding(padding: const EdgeInsets.only(bottom: 4), child: GestureDetector(
      onTap: () {
        Clipboard.setData(ClipboardData(text: phone));
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$phone nusxalandi')));
      },
      child: Row(children: [
        const Icon(Icons.phone, size: 16, color: Colors.green), const SizedBox(width: 8),
        Text(phone, style: const TextStyle(fontSize: 14, color: Colors.green, fontWeight: FontWeight.w500, decoration: TextDecoration.underline)),
        const SizedBox(width: 4), const Icon(Icons.copy, size: 12, color: Colors.green),
      ]),
    ));
  }
}
