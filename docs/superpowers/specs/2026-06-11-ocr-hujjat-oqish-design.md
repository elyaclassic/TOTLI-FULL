# OCR — Hujjatni rasmdan o'qish (Claude Vision)

**Sana:** 2026-06-11
**Holat:** Dizayn tasdiqlandi, implementatsiya kutilmoqda

## Maqsad

Ta'minotchi nakladnoyi, do'kon/bozor cheki, qo'lyozma daftar va to'lov
kvitansiyasini **rasmdan o'qib**, strukturalangan ma'lumotga aylantirish va
qo'lda kiritish vaqtini tejash. Matn aralash (lotin + kirill + raqam) bo'lishi
mumkin, jumladan qo'lyozma.

## Yondashuv

**Claude CLI Vision** (Yondashuv A). Mavjud Max obuna orqali `claude` CLI
ishlatiladi (`senior_bot/claude_client.py` patterni) — Anthropic API krediti
yo'q, qo'shimcha xarajat yo'q. Klassik offline OCR (PaddleOCR/Tesseract) rad
etildi: aralash til + qo'lyozmada juda zaif (30-50% xato) va 8GB RAM serverda
og'ir.

## Arxitektura

```
   Telegram rasm ──┐
                   ├──► ocr_service.py ──► Claude CLI ──► JSON (dict)
   Web upload   ──┘     (subprocess,        (--print,
                         timeout)            vision prompt)
                              │
                              ▼
                   Inson TASDIQLAYDI (Telegram tugma / web forma)
                              │ tasdiqlangach
                              ▼
                          DB ga yoziladi
```

**Asosiy prinsip:** OCR natijasi ishonchsiz manba. Moliyaviy bazaga
(narx/miqdor/valyuta) **hech qachon avtomatik yozilmaydi** — inson ko'rib
tasdiqlashi shart.

## JSON sxema (Claude qaytaradi)

```json
{
  "hujjat_turi": "nakladnoy | chek | qolyozma | kvitansiya | nomalum",
  "ishonch": "yuqori | orta | past",
  "sana": "2026-06-11",
  "taminotchi": "matn yoki null",
  "valyuta": "UZS | USD",
  "tolov_turi": "naqd | otkazma | qarz | nomalum",
  "qatorlar": [
    { "nomi": "Shakar", "miqdor": 50, "birlik": "kg", "narx": 12000, "summa": 600000 }
  ],
  "jami_summa": 600000,
  "ogohlantirish": "o'qilmagan joylar izohi yoki null"
}
```

**Qarorlar:**
- Maydon kalitlari ASCII/lotin (JSON parse + DB mapping xavfsizligi).
- `qatorlar` har doim massiv (bitta sxema barcha hujjatga).
- Raqamlar son sifatida (string emas) — to'g'ridan-to'g'ri forma/DB mos.
- `ishonch` past bo'lsa tasdiqlashda ajratib ko'rsatiladi (qizil/sariq).
- `valyuta` alohida e'tibor: USD↔UZS xatosi moliyaviy katta xato beradi.
- Claude **o'zi** hujjat turini aniqlaydi — foydalanuvchi qo'lda tanlamaydi.

## Komponentlar (yangi/o'zgaradigan)

| Fayl | Vazifa |
|------|--------|
| `app/services/ocr_service.py` | 🆕 Yadro: rasm → Claude CLI → JSON parse + validatsiya |
| `app/routes/api_ocr.py` | 🆕 Web endpoint `/api/ocr/parse` (rasm upload → JSON) |
| `app/bot/handlers/ocr.py` | 🆕 Telegram rasm handler + tasdiqlash FSM |
| Xarid formasi template | ✏️ "📷 Rasmdan to'ldirish" tugmasi + JS autofill |

## Service yadro mantig'i (`ocr_service.py`)

1. Rasmni vaqtinchalik faylga saqlaydi (CLI fayl yo'lini oladi).
2. `claude --print` ni vision prompt bilan subprocess sifatida chaqiradi
   (~15-30s timeout).
3. Prompt qat'iy: "FAQAT JSON qaytar, izoh yozma".
4. Javobdan JSON blokini ajratib oladi (himoya: matn aralashsa ham), parse +
   validatsiya qiladi.
5. Vaqtinchalik faylni o'chiradi (finally).

## Integratsiya oqimlari

**Telegram:**
1. Rasm yuboriladi → "⏳ O'qiyapman..."
2. `ocr_service` → natija chiroyli matn (jadval, past-ishonch ⚠️).
3. Inline tugmalar: ✅ Tasdiqlash / ✏️ Tahrirlash / ❌ Bekor.
4. Tasdiqlangach tegishli hujjatga yoziladi.

**Web:**
1. Xarid formasida `📷 Rasmdan to'ldirish` tugmasi.
2. Rasm upload → AJAX → `/api/ocr/parse` → `ocr_service`.
3. Forma maydonlari avtomatik to'ladi (qatorlar jadval), past-ishonch sariq fon.
4. Foydalanuvchi ko'rib/tahrirlab odatdagidek **Saqlash**.

## Xatolik boshqaruvi

- Claude CLI timeout/xato → "O'qib bo'lmadi, qayta urinib ko'ring yoki qo'lda
  kiriting" (jim yiqilmaslik).
- JSON parse xato → xom javob log'ga, foydalanuvchiga aniq xabar.
- Past ishonch → bloklamaydi, ogohlantiradi (foydalanuvchi qaror qiladi).

## Qamrov tashqarisi (hozircha)

- Avtomatik DB yozish (inson tasdig'isiz) — QILINMAYDI.
- Offline OCR / local model — rad etildi.
- Commit/build trigger emas.

## Sinov rejasi

- `ocr_service` uchun test skript: namuna rasmlar (nakladnoy, chek, qo'lyozma,
  kvitansiya) → JSON chiqishini tekshirish.
- Telegram: real rasm yuborib tasdiqlash oqimini sinash.
- Web: forma autofill + saqlash oqimini sinash.
