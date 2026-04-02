import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';

class KassaScreen extends StatefulWidget {
  const KassaScreen({super.key});

  @override
  State<KassaScreen> createState() => _KassaScreenState();
}

class _KassaScreenState extends State<KassaScreen> {
  final SessionService _session = SessionService();
  List<Map<String, dynamic>> _payments = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadPayments();
  }

  Future<void> _loadPayments() async {
    setState(() => _isLoading = true);
    final token = await _session.getToken();
    if (token == null) return;
    final result = await ApiService.getAgentPayments(token);
    if (mounted) {
      setState(() {
        _isLoading = false;
        if (result['success'] == true) {
          _payments = List<Map<String, dynamic>>.from(result['payments'] ?? []);
        }
      });
    }
  }

  Future<void> _createPayment() async {
    final token = await _session.getToken();
    if (token == null) return;
    final partnersResult = await ApiService.getPartners(token);
    if (!mounted) return;
    final partners = List<Map<String, dynamic>>.from(partnersResult['partners'] ?? []);

    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => _CreatePaymentSheet(partners: partners, token: token),
    );
    if (result == true) _loadPayments();
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

  String _formatDate(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    try {
      final dt = DateTime.parse(iso);
      return '${dt.day.toString().padLeft(2, '0')}.${dt.month.toString().padLeft(2, '0')}.${dt.year} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return iso;
    }
  }

  @override
  Widget build(BuildContext context) {
    final pending = _payments.where((p) => p['status'] == 'pending').toList();
    final confirmed = _payments.where((p) => p['status'] == 'confirmed').toList();
    final cancelled = _payments.where((p) => p['status'] == 'cancelled').toList();

    return Scaffold(
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _payments.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.account_balance_wallet_outlined, size: 64, color: Colors.grey[400]),
                      const SizedBox(height: 16),
                      const Text('To\'lovlar yo\'q', style: TextStyle(color: Colors.grey)),
                      const SizedBox(height: 8),
                      const Text('Mijozdan pul olganingizda\nshu yerda to\'ldiring', textAlign: TextAlign.center, style: TextStyle(color: Colors.grey, fontSize: 12)),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadPayments,
                  child: ListView(
                    children: [
                      if (pending.isNotEmpty) ...[
                        _sectionTitle('Kutilmoqda', Colors.orange, pending.length),
                        ...pending.map(_buildPaymentTile),
                      ],
                      if (confirmed.isNotEmpty) ...[
                        _sectionTitle('Tasdiqlangan', Colors.green, confirmed.length),
                        ...confirmed.map(_buildPaymentTile),
                      ],
                      if (cancelled.isNotEmpty) ...[
                        _sectionTitle('Bekor qilingan', Colors.red, cancelled.length),
                        ...cancelled.map(_buildPaymentTile),
                      ],
                      const SizedBox(height: 80),
                    ],
                  ),
                ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _createPayment,
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add),
        label: const Text('To\'lov qo\'shish'),
      ),
    );
  }

  Widget _sectionTitle(String title, Color color, int count) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Row(
        children: [
          Container(width: 4, height: 16, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2))),
          const SizedBox(width: 8),
          Text('$title ($count)', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: color)),
        ],
      ),
    );
  }

  Widget _buildPaymentTile(Map<String, dynamic> p) {
    final status = p['status'] ?? 'pending';
    final statusColor = status == 'confirmed' ? Colors.green : status == 'cancelled' ? Colors.red : Colors.orange;
    final statusText = status == 'confirmed' ? 'Tasdiqlangan' : status == 'cancelled' ? 'Bekor' : 'Kutilmoqda';
    final payType = p['payment_type'] ?? 'naqd';
    final payIcon = payType == 'plastik' ? Icons.credit_card : payType == 'perechisleniye' ? Icons.account_balance : Icons.money;
    final payLabel = payType == 'plastik' ? 'Plastik' : payType == 'perechisleniye' ? 'Perechisl.' : 'Naqd';

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: statusColor.withOpacity(0.15),
              child: Icon(payIcon, color: statusColor, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(p['partner_name'] ?? '', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      Text(payLabel, style: TextStyle(fontSize: 11, color: Colors.grey[600])),
                      const SizedBox(width: 8),
                      Text(_formatDate(p['created_at']), style: TextStyle(fontSize: 11, color: Colors.grey[500])),
                    ],
                  ),
                  if ((p['notes'] ?? '').isNotEmpty)
                    Text(p['notes'], style: TextStyle(fontSize: 11, color: Colors.grey[500]), maxLines: 1, overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text('${_formatMoney((p['amount'] ?? 0).toDouble())}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                Text(statusText, style: TextStyle(fontSize: 10, color: statusColor)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CreatePaymentSheet extends StatefulWidget {
  final List<Map<String, dynamic>> partners;
  final String token;
  const _CreatePaymentSheet({required this.partners, required this.token});

  @override
  State<_CreatePaymentSheet> createState() => _CreatePaymentSheetState();
}

class _CreatePaymentSheetState extends State<_CreatePaymentSheet> {
  int? _selectedPartnerId;
  final _naqdController = TextEditingController();
  final _plastikController = TextEditingController();
  final _perController = TextEditingController();
  final _notesController = TextEditingController();
  bool _isSending = false;

  double get _naqd => double.tryParse(_naqdController.text.trim()) ?? 0;
  double get _plastik => double.tryParse(_plastikController.text.trim()) ?? 0;
  double get _per => double.tryParse(_perController.text.trim()) ?? 0;
  double get _total => _naqd + _plastik + _per;

  Future<void> _submit() async {
    if (_selectedPartnerId == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mijozni tanlang')));
      return;
    }
    if (_total <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Summani kiriting')));
      return;
    }
    setState(() => _isSending = true);

    // Har bir to'lov turi uchun alohida so'rov
    int sent = 0;
    String? lastError;
    for (final entry in [
      {'type': 'naqd', 'amount': _naqd},
      {'type': 'plastik', 'amount': _plastik},
      {'type': 'perechisleniye', 'amount': _per},
    ]) {
      if ((entry['amount'] as double) <= 0) continue;
      final result = await ApiService.createAgentPayment(widget.token, {
        'partner_id': _selectedPartnerId,
        'amount': entry['amount'],
        'payment_type': entry['type'],
        'notes': _notesController.text.trim(),
      });
      if (result['success'] == true) {
        sent++;
      } else {
        lastError = result['error']?.toString();
      }
    }

    if (!mounted) return;
    setState(() => _isSending = false);
    if (sent > 0) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$sent ta to\'lov qo\'shildi'), backgroundColor: Colors.green));
      Navigator.pop(context, true);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(lastError ?? 'Xato'), backgroundColor: Colors.red));
    }
  }

  @override
  void dispose() {
    _naqdController.dispose();
    _plastikController.dispose();
    _perController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  String _fmt(double v) { if (v <= 0) return '0'; final s = v.toInt().toString(); final b = StringBuffer(); for (int i = 0; i < s.length; i++) { if (i > 0 && (s.length - i) % 3 == 0) b.write(' '); b.write(s[i]); } return b.toString(); }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(left: 16, right: 16, top: 16, bottom: MediaQuery.of(context).viewInsets.bottom + 16),
      child: SingleChildScrollView(child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(2)))),
          const SizedBox(height: 12),
          const Text('Yangi to\'lov', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          // Mijoz qidirish
          GestureDetector(
            onTap: () async {
              final selected = await showModalBottomSheet<Map<String, dynamic>>(
                context: context,
                isScrollControlled: true,
                shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
                builder: (ctx) => _PartnerSearchSheet(partners: widget.partners),
              );
              if (selected != null) {
                setState(() => _selectedPartnerId = selected['id'] as int);
              }
            },
            child: InputDecorator(
              decoration: InputDecoration(
                labelText: 'Mijoz',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                isDense: true,
                suffixIcon: const Icon(Icons.search),
              ),
              child: Text(
                _selectedPartnerId != null
                    ? (widget.partners.firstWhere((p) => p['id'] == _selectedPartnerId, orElse: () => {'name': '?'})['name'] ?? '?')
                    : 'Tanlang...',
                style: TextStyle(color: _selectedPartnerId != null ? Colors.black : Colors.grey),
              ),
            ),
          ),
          const SizedBox(height: 12),
          // Naqd
          TextField(
            controller: _naqdController,
            keyboardType: TextInputType.number,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: 'Naqd',
              hintText: '0',
              prefixIcon: const Icon(Icons.money, color: Colors.green, size: 20),
              suffixText: 'so\'m',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              isDense: true,
            ),
          ),
          const SizedBox(height: 10),
          // Plastik
          TextField(
            controller: _plastikController,
            keyboardType: TextInputType.number,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: 'Plastik',
              hintText: '0',
              prefixIcon: const Icon(Icons.credit_card, color: Colors.blue, size: 20),
              suffixText: 'so\'m',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              isDense: true,
            ),
          ),
          const SizedBox(height: 10),
          // Perechisleniye
          TextField(
            controller: _perController,
            keyboardType: TextInputType.number,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: 'Perechisl. (bank)',
              hintText: '0',
              prefixIcon: const Icon(Icons.account_balance, color: Colors.purple, size: 20),
              suffixText: 'so\'m',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              isDense: true,
            ),
          ),
          if (_total > 0) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(color: Colors.green.shade50, borderRadius: BorderRadius.circular(10)),
              child: Row(children: [
                const Icon(Icons.calculate, color: Colors.green, size: 20),
                const SizedBox(width: 8),
                const Text('Jami: '),
                Text('${_fmt(_total)} so\'m', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.green)),
              ]),
            ),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: _notesController,
            decoration: InputDecoration(
              labelText: 'Izoh (ixtiyoriy)',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
              isDense: true,
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _isSending ? null : _submit,
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF017449),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: _isSending
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Text('Yuborish', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          ),
        ],
      )),
    );
  }
}

class _PartnerSearchSheet extends StatefulWidget {
  final List<Map<String, dynamic>> partners;
  const _PartnerSearchSheet({required this.partners});
  @override
  State<_PartnerSearchSheet> createState() => _PartnerSearchSheetState();
}

class _PartnerSearchSheetState extends State<_PartnerSearchSheet> {
  String _query = '';

  List<Map<String, dynamic>> get _filtered {
    if (_query.isEmpty) return widget.partners;
    final q = _query.toLowerCase();
    return widget.partners.where((p) => (p['name'] ?? '').toString().toLowerCase().contains(q)).toList();
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.7,
      maxChildSize: 0.9,
      minChildSize: 0.4,
      expand: false,
      builder: (ctx, scrollController) => Column(children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: TextField(
            autofocus: true,
            onChanged: (v) => setState(() => _query = v),
            decoration: InputDecoration(
              hintText: 'Mijoz qidirish...',
              prefixIcon: const Icon(Icons.search),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
              isDense: true,
            ),
          ),
        ),
        Expanded(
          child: ListView.builder(
            controller: scrollController,
            itemCount: _filtered.length,
            itemBuilder: (ctx, i) {
              final p = _filtered[i];
              return ListTile(
                dense: true,
                title: Text(p['name'] ?? '', style: const TextStyle(fontWeight: FontWeight.w500)),
                subtitle: (p['phone'] ?? '').toString().isNotEmpty ? Text(p['phone']) : null,
                onTap: () => Navigator.pop(ctx, p),
              );
            },
          ),
        ),
      ]),
    );
  }
}
