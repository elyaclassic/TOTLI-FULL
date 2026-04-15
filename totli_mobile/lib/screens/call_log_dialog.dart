import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';

/// Qo'ng'iroq boshlab berish va qaytganda jurnalga yozish oqimi.
/// Agent `startCallAndLog` ni chaqiradi — `tel:` URL ochiladi va
/// qaytganda natija + izoh modal ochiladi.
class CallLogFlow {
  static Future<void> startCallAndLog({
    required BuildContext context,
    required String phone,
    required String partnerName,
    int? partnerId,
  }) async {
    if (phone.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Telefon raqami yo\'q'), backgroundColor: Colors.orange),
      );
      return;
    }

    final startedAt = DateTime.now();

    // Qo'ng'iroq ochiladi
    final uri = Uri.parse('tel:${phone.replaceAll(' ', '')}');
    try {
      final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!ok) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Qo\'ng\'iroq ochilmadi'), backgroundColor: Colors.red),
          );
        }
        return;
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Qo\'ng\'iroq xatosi: $e'), backgroundColor: Colors.red),
        );
      }
      return;
    }

    // Foydalanuvchi qaytguncha kutamiz. Flutter telefon ilovasiga o'tganda ilova
    // background ga tushadi; shu vaqtni hisoblash uchun — qaytganda ish davom etadi.
    // Taxminiy davomiylik — (endi - startedAt).
    // Soddalik uchun dialog ni darhol ko'rsatamiz (qaytganda).
    // Agar ilova background'da bo'lsa, dialog qaytganda paydo bo'ladi.

    // Kichik kechikish — tizim tel ilovasini ochishi uchun
    await Future.delayed(const Duration(milliseconds: 800));

    if (!context.mounted) return;

    final durationSec = DateTime.now().difference(startedAt).inSeconds;
    await _showLogDialog(
      context: context,
      phone: phone,
      partnerName: partnerName,
      partnerId: partnerId,
      approximateDurationSec: durationSec,
    );
  }

  static Future<void> _showLogDialog({
    required BuildContext context,
    required String phone,
    required String partnerName,
    int? partnerId,
    required int approximateDurationSec,
  }) async {
    final formKey = GlobalKey<FormState>();
    String result = 'answered';
    final notesCtrl = TextEditingController();
    final durationCtrl = TextEditingController(text: approximateDurationSec.toString());

    final results = [
      {'key': 'answered', 'label': 'Javob berdi', 'icon': Icons.check_circle, 'color': Colors.green},
      {'key': 'order', 'label': 'Buyurtma oldi', 'icon': Icons.shopping_cart, 'color': Colors.blue},
      {'key': 'no_answer', 'label': 'Javob bermadi', 'icon': Icons.phone_missed, 'color': Colors.orange},
      {'key': 'rejected', 'label': 'Rad qildi', 'icon': Icons.block, 'color': Colors.red},
      {'key': 'later', 'label': 'Keyinroq', 'icon': Icons.schedule, 'color': Colors.purple},
      {'key': 'refused', 'label': 'Olmaydi', 'icon': Icons.thumb_down, 'color': Colors.brown},
    ];

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          title: Row(children: [
            const Icon(Icons.phone_in_talk, color: Color(0xFF017449)),
            const SizedBox(width: 8),
            Expanded(child: Text('Qo\'ng\'iroq natijasi', style: const TextStyle(fontSize: 16))),
          ]),
          content: SingleChildScrollView(
            child: Form(
              key: formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(partnerName, style: const TextStyle(fontWeight: FontWeight.bold)),
                  Text(phone, style: TextStyle(color: Colors.grey[600], fontSize: 13)),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: durationCtrl,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Davomiyligi (sekundda)',
                      prefixIcon: Icon(Icons.timer, size: 18),
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  const Text('Natija:', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: results.map((r) {
                      final selected = result == r['key'];
                      final color = r['color'] as Color;
                      return GestureDetector(
                        onTap: () => setState(() => result = r['key'] as String),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                          decoration: BoxDecoration(
                            color: selected ? color : color.withOpacity(0.08),
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(color: color, width: selected ? 2 : 1),
                          ),
                          child: Row(mainAxisSize: MainAxisSize.min, children: [
                            Icon(r['icon'] as IconData, size: 14, color: selected ? Colors.white : color),
                            const SizedBox(width: 4),
                            Text(
                              r['label'] as String,
                              style: TextStyle(
                                color: selected ? Colors.white : color,
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ]),
                        ),
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: notesCtrl,
                    maxLines: 3,
                    decoration: const InputDecoration(
                      labelText: 'Izoh (nima haqida gaplashdingiz)',
                      hintText: 'Narxdan shikoyat, yangi buyurtma, keyingi hafta...',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Bekor qilish'),
            ),
            ElevatedButton(
              onPressed: () async {
                final durationSec = int.tryParse(durationCtrl.text.trim()) ?? approximateDurationSec;
                Navigator.pop(ctx);

                final token = await SessionService().getToken();
                if (token == null) return;

                Position? pos;
                try {
                  pos = await Geolocator.getCurrentPosition(
                    desiredAccuracy: LocationAccuracy.high,
                    timeLimit: const Duration(seconds: 5),
                  );
                } catch (_) {}

                final r = await ApiService.logCall(
                  token,
                  partnerId: partnerId,
                  phone: phone,
                  durationSec: durationSec,
                  result: result,
                  notes: notesCtrl.text.trim().isEmpty ? null : notesCtrl.text.trim(),
                  latitude: pos?.latitude,
                  longitude: pos?.longitude,
                );

                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(r['success'] == true ? 'Qo\'ng\'iroq saqlandi' : 'Saqlashda xato'),
                      backgroundColor: r['success'] == true ? Colors.green : Colors.red,
                    ),
                  );
                }
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF017449),
                foregroundColor: Colors.white,
              ),
              child: const Text('Saqlash'),
            ),
          ],
        ),
      ),
    );
  }
}
