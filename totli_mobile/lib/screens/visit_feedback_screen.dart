import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';

/// Vizit yakunida (check-out) ko'rinadigan feedback ekrani.
/// Mijoz fikri, agent kuzatuvi, muammo bor-yo'qligi saqlanadi.
class VisitFeedbackScreen extends StatefulWidget {
  final int visitId;
  final String partnerName;

  const VisitFeedbackScreen({
    super.key,
    required this.visitId,
    required this.partnerName,
  });

  @override
  State<VisitFeedbackScreen> createState() => _VisitFeedbackScreenState();
}

class _VisitFeedbackScreenState extends State<VisitFeedbackScreen> {
  final _customerCtrl = TextEditingController();
  final _agentCtrl = TextEditingController();
  final _problemCtrl = TextEditingController();
  bool _hasProblem = false;
  bool _busy = false;

  // Tez tanlov tugmalari
  static const List<String> _customerQuicks = [
    'Narx past bo\'lsin',
    'Yangi mahsulot kerak',
    'Yetkazish tez bo\'lsin',
    'Sifat yaxshi',
    'Qadoq yomon',
    'Sotuv yomon',
  ];

  static const List<String> _agentQuicks = [
    'Qarz oshdi',
    'Yaxshi hamkor',
    'Raqobatchidan oladi',
    'Yangi nuqta ochmoqchi',
    'Diqqat talab',
  ];

  void _toggleCustomer(String text) {
    final current = _customerCtrl.text;
    if (current.contains(text)) return;
    _customerCtrl.text = current.isEmpty ? text : '$current, $text';
    _customerCtrl.selection = TextSelection.fromPosition(TextPosition(offset: _customerCtrl.text.length));
  }

  void _toggleAgent(String text) {
    final current = _agentCtrl.text;
    if (current.contains(text)) return;
    _agentCtrl.text = current.isEmpty ? text : '$current, $text';
    _agentCtrl.selection = TextSelection.fromPosition(TextPosition(offset: _agentCtrl.text.length));
  }

  Future<void> _save({bool withCheckout = true}) async {
    setState(() => _busy = true);
    final token = await SessionService().getToken();
    if (token == null) {
      setState(() => _busy = false);
      return;
    }

    // Feedback ni saqlash
    await ApiService.saveVisitFeedback(
      token,
      visitId: widget.visitId,
      customerFeedback: _customerCtrl.text.trim(),
      agentNotes: _agentCtrl.text.trim(),
      problemDescription: _hasProblem ? _problemCtrl.text.trim() : '',
      hasProblem: _hasProblem,
    );

    // Check-out qilish
    if (withCheckout) {
      await ApiService.checkOut(token, visitId: widget.visitId);
    }

    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Vizit yakunlandi'), backgroundColor: Colors.green),
    );
    Navigator.pop(context, true);
  }

  @override
  void dispose() {
    _customerCtrl.dispose();
    _agentCtrl.dispose();
    _problemCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvoked: (didPop) async {
        if (didPop) return;
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('Chiqib ketasizmi?'),
            content: const Text('Vizit yakunlanmadi. Keyinroq qaytish uchun kechiktirishingiz mumkin.'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Qolish')),
              TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Chiqish', style: TextStyle(color: Colors.orange)),
              ),
            ],
          ),
        );
        if (ok == true && mounted) Navigator.pop(context, false);
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(widget.partnerName, style: const TextStyle(fontSize: 15)),
          backgroundColor: const Color(0xFF017449),
          foregroundColor: Colors.white,
        ),
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.blue.shade50,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(children: [
                  Icon(Icons.task_alt, color: Colors.blue.shade700),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text('Vizit yakunlanmoqda. Quyidagi ma\'lumotlarni to\'ldiring.', style: TextStyle(fontSize: 13)),
                  ),
                ]),
              ),
              const SizedBox(height: 20),

              // Mijoz fikri
              const Text('1. Mijoz fikri / talabi', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: _customerQuicks.map((q) => ActionChip(
                  label: Text(q, style: const TextStyle(fontSize: 11)),
                  onPressed: () => _toggleCustomer(q),
                  backgroundColor: Colors.orange.shade50,
                  side: BorderSide(color: Colors.orange.shade200),
                )).toList(),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _customerCtrl,
                maxLines: 3,
                decoration: const InputDecoration(
                  hintText: 'Mijoz nimani istayapti...',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 20),

              // Agent kuzatuvi
              const Text('2. Agent kuzatuvi / tavsiyasi', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: _agentQuicks.map((q) => ActionChip(
                  label: Text(q, style: const TextStyle(fontSize: 11)),
                  onPressed: () => _toggleAgent(q),
                  backgroundColor: Colors.green.shade50,
                  side: BorderSide(color: Colors.green.shade200),
                )).toList(),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _agentCtrl,
                maxLines: 3,
                decoration: const InputDecoration(
                  hintText: 'Kuzatuv va tavsiyangiz...',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 20),

              // Muammo
              const Text('3. Muammo bormi?', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
              const SizedBox(height: 6),
              SwitchListTile(
                value: _hasProblem,
                onChanged: (v) => setState(() => _hasProblem = v),
                title: Text(_hasProblem ? 'Ha, muammo bor' : 'Yo\'q, muammo yo\'q'),
                activeColor: Colors.red,
                contentPadding: EdgeInsets.zero,
              ),
              if (_hasProblem) ...[
                const SizedBox(height: 4),
                TextField(
                  controller: _problemCtrl,
                  maxLines: 3,
                  decoration: InputDecoration(
                    hintText: 'Muammoni tavsiflang...',
                    border: const OutlineInputBorder(),
                    filled: true,
                    fillColor: Colors.red.shade50,
                  ),
                ),
              ],
              const SizedBox(height: 30),

              // Tugmalar
              Row(children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _busy ? null : () => _save(withCheckout: true),
                    icon: _busy
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Icon(Icons.check_circle),
                    label: const Text('Saqlash va yakunlash'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF017449),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
              ]),
            ],
          ),
        ),
      ),
    );
  }
}
