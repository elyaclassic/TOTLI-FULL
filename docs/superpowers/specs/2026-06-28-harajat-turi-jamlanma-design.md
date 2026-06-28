# Harajat turi bo'yicha filtr + jamlanma — Dizayn

**Sana:** 2026-06-28
**Sahifa:** `/finance/harajatlar` (Harajatlar jurnali)
**Maqsad:** Foydalanuvchi harajatlarni *haqiqiy harajat turi* bo'yicha filtrlay olishi va har bir tur qancha summa bo'lganini ko'ra olishi.

## Muammo

Hozirgi "Tur" dropdown (`kind`) faqat hujjat *manbasini* (HD / xarid / boshqa) ajratadi — bu harajat turi emas. Foydalanuvchi esa "ish haqqi 15M, oziq-ovqat 8M" kabi tur kesimini ko'rishni xohlaydi.

## Ma'lumotlar tuzilishi (mavjud)

Tizimda ikki xil "tur" tushunchasi bor:

1. **`ExpenseType`** — foydalanuvchi yaratadigan harajat turlari (ish haqqi, oziq-ovqat, Yolkiro). Faqat HD hujjatlarida ishlatiladi.
   - `ExpenseDoc` (hujjat) → bir nechta `ExpenseDocItem`
   - Har `ExpenseDocItem`: `expense_type_id` (FK → ExpenseType) + `amount`
   - **Muhim:** tur qator (item) darajasida — bitta HD'da bir nechta xil tur bo'lishi mumkin.

2. **`Payment.category`** — tizim kodlari: `expense`, `other`, `sale_return`, `delivery`, `agent_collection`, `purchase_expense`, `NULL`. PAY chiqimlarida ishlatiladi.

HD tasdiqlanganda bog'langan `Payment` yaratiladi (`ExpenseDoc.payment_id`). Hisob-kitobda double-count'ni oldini olish uchun PAY tomoni HD bilan bog'langan payment'larni chiqarib tashlaydi (`hd_payment_ids`).

## Yechim

### 1. Filtr: "Tur" → "Harajat turi"

Mavjud `kind` dropdown o'rniga birlashtirilgan `etype` dropdown. Ikki guruhli (`<optgroup>`):

- **Harajat turlari (HD)** — barcha aktiv `ExpenseType`. Qiymat: `et:<id>`
- **To'lov kategoriyalari (PAY)** — friendly label'li kategoriyalar. Qiymat: `cat:<code>`

PAY kategoriya → label xaritasi:

| code | label |
|------|-------|
| `expense` | Oddiy harajat |
| `other` | Boshqa to'lov |
| `sale_return` | Sotuv qaytarish |
| `delivery` | Yetkazib berish |
| `agent_collection` | Agent inkassa |
| `purchase_expense` | Xarid xarajati |
| `NULL` / boshqa | Turkumlanmagan (yoki raw code) |

Filtr xatti-harakati:
- `et:<id>` tanlansa → faqat shu turdagi qatori bor HD hujjatlari ko'rinadi; PAY ro'yxati bo'shaydi.
- `cat:<code>` tanlansa → faqat shu kategoriyali PAY to'lovlari; HD ro'yxati bo'shaydi.

### 2. "Tur bo'yicha jamlanma" jadvali

Statistika kartalaridan keyin yangi jadval. Ustunlar: **Tur | Manba | Soni | Summa | Ulush %**.

Hisoblash (ikki manbadan, double-count'siz):

- **HD turlari:** `ExpenseDocItem.amount` ni `expense_type_id` bo'yicha SUM/COUNT. Faqat tasdiqlangan (`status='confirmed'`) hujjatlar, joriy filtr oralig'ida (sana/kassa/yo'nalish/bo'lim).
- **PAY kategoriyalari:** HD bilan bog'lanmagan `Payment.amount` (type='expense', status confirmed/NULL, `category != 'audit_correction'`) ni `category` bo'yicha SUM/COUNT.

Natija summa bo'yicha kamayish tartibida saralanadi. Har qator ulushi = summa / JAMI × 100. JAMI qatori = mavjud "JAMI chiqim" kartasi (898M) bilan **aniq mos keladi**.

### 3. Boshqa filtrlar bilan o'zaro ta'sir

- Jamlanma barcha mavjud filtrlarga bo'ysunadi (Dan/Gacha, Kassa, Yo'nalish, Bo'lim) — `_apply_stat_filters` va `stat_from`/`stat_to_excl` bilan bir xil oraliq.
- Sana qamrovi: filtr bo'lmasa "bugun", filtr bo'lsa o'sha oraliq.
- Harajat turi filtri tanlansa, jamlanma ham faqat o'sha turni ko'rsatadi (bitta qator).
- Bekor qilingan (`cancelled`) to'lovlar jamlanmaga kirmaydi.

## Cheklovlar (YAGNI)

- Oylik va avans ko'pincha bir xil PAY kategoriyasida (`expense`) — bu bosqichda kategoriya darajasida guruhlanadi, oylik/avans alohida ajralmaydi.
- Excel eksport va grafik (pie chart) bu bosqichda **qo'shilmaydi** — keyingi bosqich.

## O'zgaradigan fayllar

- `app/routes/finance.py` — `finance_harajatlar`:
  - `kind` parametri → `etype` (yoki `etype` qo'shib `kind` deprecate)
  - HD va PAY filtr mantig'ini `etype` ga moslash
  - jamlanma agregatsiyasini hisoblab template'ga uzatish (`type_breakdown`, `expense_types` ro'yxati, `pay_categories` label xaritasi)
- `app/templates/finance/harajatlar.html`:
  - "Tur" dropdown → "Harajat turi" (optgroup'li)
  - yangi "Tur bo'yicha jamlanma" jadvali bo'limi

## Muvaffaqiyat mezoni

- "Harajat turi" dropdown HD turlari + PAY kategoriyalarini ko'rsatadi.
- Tur tanlanганda ro'yxatlar to'g'ri filtrlanadi.
- Jamlanma jadvali har turning summasi va ulushini ko'rsatadi; JAMI "JAMI chiqim" kartasi bilan mos.
- Barcha mavjud filtrlar (sana/kassa/yo'nalish/bo'lim) jamlanmaga ham ta'sir qiladi.
