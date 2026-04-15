import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';

/// Ilova ichidan SMS yozish va yuborish ekrani.
/// Tizim SMS ilovasi ochiladi, yuborilgandan so'ng jurnalga yoziladi.
class SmsComposeScreen extends StatefulWidget {
  final int? partnerId;
  final String partnerName;
  final String phone;

  const SmsComposeScreen({
    super.key,
    this.partnerId,
    required this.partnerName,
    required this.phone,
  });

  @override
  State<SmsComposeScreen> createState() => _SmsComposeScreenState();
}

class _SmsComposeScreenState extends State<SmsComposeScreen> {
  final _messageCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  String _selectedTemplate = 'custom';
  bool _busy = false;

  // Shablonlar
  static const Map<String, Map<String, String>> _templates = {
    'greeting': {
      'label': 'Salom',
      'text': 'Assalomu alaykum! Bu TOTLI HOLVA agenti. Ertaga sizga uchrashuv uchun borsam maylimi?',
    },
    'order_confirm': {
      'label': 'Buyurtma tasdiqi',
      'text': 'Buyurtmangiz qabul qilindi. Yetkazib berish bugun-ertaga amalga oshadi. Rahmat!',
    },
    'debt': {
      'label': 'Qarz eslatmasi',
      'text': 'Hurmatli mijoz, sizning qarzingiz bo\'yicha eslatma. Iltimos, imkon bo\'lgan muddatda to\'lashni iltimos qilamiz.',
    },
    'followup': {
      'label': 'Keyingi aloqa',
      'text': 'Bizning mahsulotlar qanday ketyapti? Yangi buyurtma bera olsamkimi, xabar bering.',
    },
    'custom': {
      'label': 'Bo\'sh',
      'text': '',
    },
  };

  void _selectTemplate(String key) {
    setState(() {
      _selectedTemplate = key;
      _messageCtrl.text = _templates[key]?['text'] ?? '';
    });
  }

  Future<void> _sendAndLog() async {
    final msg = _messageCtrl.text.trim();
    if (msg.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Xabar matni bo\'sh'), backgroundColor: Colors.orange),
      );
      return;
    }
    setState(() => _busy = true);

    // Tizim SMS ilovasi orqali yuborish
    final uri = Uri.parse('sms:${widget.phone.replaceAll(' ', '')}?body=${Uri.encodeComponent(msg)}');
    bool launched = false;
    try {
      launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {}

    if (!launched) {
      if (!mounted) return;
      setState(() => _busy = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('SMS ilovasini ochib bo\'lmadi'), backgroundColor: Colors.red),
      );
      return;
    }

    // Serverga jurnalga yozish (yuborilgan deb hisoblaymiz)
    final token = await SessionService().getToken();
    if (token != null) {
      await ApiService.logSms(
        token,
        partnerId: widget.partnerId,
        phone: widget.phone,
        message: msg,
        template: _selectedTemplate,
        notes: _notesCtrl.text.trim().isEmpty ? null : _notesCtrl.text.trim(),
      );
    }

    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('SMS yuborildi va jurnalga yozildi'), backgroundColor: Colors.green),
    );
    Navigator.pop(context, true);
  }

  @override
  void dispose() {
    _messageCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final charCount = _messageCtrl.text.length;
    final smsCount = (charCount / 160).ceil().clamp(1, 10);

    return Scaffold(
      appBar: AppBar(
        title: const Text('SMS yuborish', style: TextStyle(fontSize: 16)),
        backgroundColor: const Color(0xFF017449),
        foregroundColor: Colors.white,
      ),
      body: Column(
        children: [
          Container(
            width: double.infinity,
            color: Colors.grey.shade100,
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.partnerName, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                Text(widget.phone, style: TextStyle(color: Colors.grey[700], fontSize: 13)),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
            child: Row(children: [
              const Text('Shablon: ', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(width: 6),
              Expanded(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: _templates.entries.map((e) {
                      final selected = _selectedTemplate == e.key;
                      return Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: ChoiceChip(
                          label: Text(e.value['label'] ?? e.key),
                          selected: selected,
                          onSelected: (_) => _selectTemplate(e.key),
                          selectedColor: const Color(0xFF017449),
                          labelStyle: TextStyle(
                            color: selected ? Colors.white : Colors.black87,
                            fontSize: 12,
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ),
              ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _messageCtrl,
              maxLines: 6,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                labelText: 'Xabar matni',
                helperText: '$charCount ta belgi  •  ~$smsCount ta SMS',
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: TextField(
              controller: _notesCtrl,
              maxLines: 2,
              decoration: const InputDecoration(
                labelText: 'Ichki izoh (faqat siz va rahbariyat uchun)',
                hintText: 'Masalan: qarz eslatma',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
          ),
          const Spacer(),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _busy ? null : _sendAndLog,
                    icon: _busy
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Icon(Icons.send),
                    label: const Text('Yuborish'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF017449),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}
