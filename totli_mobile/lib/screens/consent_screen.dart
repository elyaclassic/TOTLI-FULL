import 'package:flutter/material.dart';

import '../services/session_service.dart';

/// Ilovaning birinchi ochilishida ko'rsatiladigan rozilik ekrani.
/// Foydalanuvchi "Roziman" bosgandan so'ng saqlanadi va qayta ko'rsatilmaydi.
class ConsentScreen extends StatefulWidget {
  /// Rozilikdan keyin ochiladigan keyingi ekran (SplashScreen allaqachon pop bo'lgan).
  final WidgetBuilder nextScreenBuilder;

  const ConsentScreen({super.key, required this.nextScreenBuilder});

  @override
  State<ConsentScreen> createState() => _ConsentScreenState();
}

class _ConsentScreenState extends State<ConsentScreen> {
  bool _checked = false;
  bool _busy = false;

  Future<void> _accept() async {
    if (_busy) return;
    setState(() => _busy = true);
    await SessionService().setConsent(true);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: widget.nextScreenBuilder),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F5F5),
      body: SafeArea(
        child: Column(
          children: [
            Container(
              width: double.infinity,
              color: const Color(0xFF017449),
              padding: const EdgeInsets.symmetric(vertical: 22, horizontal: 16),
              child: Column(
                children: [
                  const Icon(Icons.privacy_tip, color: Colors.white, size: 42),
                  const SizedBox(height: 8),
                  const Text(
                    'Shaxsiy ma\'lumotlarni yig\'ish haqida',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'TOTLI HOLVA — xizmat ilovasi',
                    style: TextStyle(color: Colors.white.withOpacity(0.85), fontSize: 13),
                  ),
                ],
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _section(
                      icon: Icons.check_circle,
                      color: Colors.green,
                      title: 'Ilova YIG\'ADI:',
                      bullets: [
                        'GPS joylashuv (ish vaqtida, vizit va yetkazish uchun)',
                        'Ilova ichida kameradan olingan rasmlar (prilavka, qoldiq, do\'kon fasadi)',
                        'Ilovadan qilingan qo\'ng\'iroqlar izohlari va davomiyligi',
                        'Ilovadan yuborilgan SMS lar matni',
                        'Vizit yakunida siz kiritgan mijoz fikri va agent izohlari',
                      ],
                    ),
                    const SizedBox(height: 14),
                    _section(
                      icon: Icons.block,
                      color: Colors.red,
                      title: 'Ilova YIG\'MAYDI va KIRMAYDI:',
                      bullets: [
                        'Shaxsiy rasmlar / galereya',
                        'Shaxsiy SMS va ilova tashqarisidagi qo\'ng\'iroqlar',
                        'Kontaktlar ro\'yxati, brauzer tarixi',
                        'Boshqa ilovalardagi ma\'lumotlar',
                      ],
                    ),
                    const SizedBox(height: 14),
                    _section(
                      icon: Icons.shield,
                      color: Colors.blue,
                      title: 'Maqsad va maxfiylik:',
                      bullets: [
                        'Ma\'lumotlar faqat TOTLI HOLVA kompaniyasining serverida saqlanadi',
                        'Faqat ish jarayoni tahlili va mijozlarga xizmat sifatini oshirish uchun ishlatiladi',
                        'Uchinchi shaxslarga berilmaydi',
                        'Rasmlar 90 kundan keyin avtomatik o\'chiriladi',
                      ],
                    ),
                    const SizedBox(height: 20),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.amber.shade50,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.amber.shade300),
                      ),
                      child: const Row(
                        children: [
                          Icon(Icons.info_outline, color: Colors.amber, size: 20),
                          SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'Ilovadan foydalanish kompaniya bilan tuzilgan mehnat shartnomasining qismidir. Savollar bo\'lsa rahbar bilan bog\'laning.',
                              style: TextStyle(fontSize: 12),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    CheckboxListTile(
                      value: _checked,
                      onChanged: (v) => setState(() => _checked = v ?? false),
                      activeColor: const Color(0xFF017449),
                      controlAffinity: ListTileControlAffinity.leading,
                      title: const Text(
                        'Men shartlarni o\'qidim va yuqoridagilarga roziman',
                        style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.all(16),
              color: Colors.white,
              child: Row(
                children: [
                  Expanded(
                    child: ElevatedButton(
                      onPressed: _checked && !_busy ? _accept : null,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF017449),
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        disabledBackgroundColor: Colors.grey.shade300,
                      ),
                      child: _busy
                          ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                          : const Text('Davom etish', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _section({required IconData icon, required Color color, required String title, required List<String> bullets}) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.grey.shade200),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 8),
            Text(title, style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: color)),
          ]),
          const SizedBox(height: 8),
          ...bullets.map((b) => Padding(
                padding: const EdgeInsets.only(left: 28, bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('•  '),
                    Expanded(child: Text(b, style: const TextStyle(fontSize: 13, height: 1.35))),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}
