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

    // GPS olish
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
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('GPS xato: $e'), backgroundColor: Colors.red));
    }
  }

  Future<void> _endVisit(Map<String, dynamic> visit) async {
    final token = await _session.getToken();
    if (token == null) return;
    final result = await ApiService.checkOut(token, visitId: visit['id']);
    if (!mounted) return;
    if (result['success'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Vizit yakunlandi'), backgroundColor: Colors.green));
      _loadData();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result['error'] ?? 'Xato'), backgroundColor: Colors.red));
    }
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
    final status = v['status'] ?? 'visited';
    final isActive = status == 'in_progress' || v['check_out_time'] == null;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      color: isActive ? Colors.green.shade50 : null,
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: isActive ? Colors.green : Colors.grey.shade200,
          child: Icon(Icons.pin_drop, color: isActive ? Colors.white : Colors.grey, size: 20),
        ),
        title: Text(v['partner_name'] ?? 'Mijoz #${v['partner_id']}', style: const TextStyle(fontWeight: FontWeight.w500)),
        subtitle: Text(
          'Kirish: ${v['check_in_time'] ?? '-'}${v['check_out_time'] != null ? ' | Chiqish: ${v['check_out_time']}' : ''}',
          style: const TextStyle(fontSize: 11),
        ),
        trailing: isActive
            ? TextButton(
                onPressed: () => _endVisit(v),
                style: TextButton.styleFrom(foregroundColor: Colors.red),
                child: const Text('Yakunlash'),
              )
            : Text(status == 'visited' ? 'Tugallangan' : status, style: const TextStyle(fontSize: 11, color: Colors.grey)),
      ),
    );
  }
}

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
                return ListTile(
                  leading: const Icon(Icons.store, color: Color(0xFF017449)),
                  title: Text(p['name'] ?? ''),
                  subtitle: Text(p['address'] ?? p['phone'] ?? '', style: const TextStyle(fontSize: 12)),
                  onTap: () => Navigator.pop(ctx, p),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
