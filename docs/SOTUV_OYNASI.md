# Sotuv oynasi va sotuvchi roli

## Sotuvchi uchun alohida POS (Sotuv oynasi) — `/sales/pos`

**Rol:** `sotuvchi`. Login qilganda avtomatik shu sahifaga yo'naltiriladi.

- **Sotuv bo'limi ombori:** Nomida yoki kodida «sotuv» bo'lgan ombor; bo'lmasa birinchi ombor ishlatiladi. Faqat shu omborda **qoldiq bor** tovarlar ko'rsatiladi.
- **Grid ko'rinishi:** Tovarlar kartochkalarda — rasm, nom, narx (narx turi bo'yicha). Tovarga bosish = savatga 1 dona qo'shiladi.
- **Savat:** O'ngda — Mahsulot, Miqdor, Narx, Summa (tahrirlanadi), o'chirish. Jami. **Sotuv** tugmasi.
- **Sotuv** bosilganda: **To'lov turi** modali — **Naqd** yoki **Plastik**. Tanlangandan keyin sotuv yaratiladi, ombor qoldig'i kamayadi, hujjat bajarilgan holatda saqlanadi (`payment_type` = naqd/plastik).
- **Default mijoz:** Kod «chakana» yoki «pos» bo'lgan kontragent; bo'lmasa birinchi kontragent.

Admin/menejer ham **Sotuvlar** yonida **Sotuv oynasi** orqali `/sales/pos` ga kirishi mumkin.

---

## Umumiy sotuv oynasi (mijoz tanlash bilan) — 3 sahifa

Sotuv oynasi **3 ta asosiy sahifa**dan iborat. Menyu: **Sotuvlar** (`/sales`).

---

## 1. Sotuvlar ro'yxati — `/sales`

- **Sarlavha:** "Sotuvlar", o'ngda **Yaratish** tugmasi.
- **Jadval:**  
  | № | Hujjat № | Sana | Mijoz | Ombor | Summa | Holat | Harakatlar |
  - Har bir sotuv: **Ochish** (tahrir sahifasiga), bajarilganida admin uchun **Tasdiqni bekor qilish**, qoralama va admin uchun **O'chirish**.
- Sotuvlar bo'lmasa: "Hozircha sotuvlar yo'q. Yangi sotuv yaratish" havolasi.

---

## 2. Yangi sotuv (asosiy sotuv oynasi) — `/sales/new`

Bu sahifa **sotuvchi tovar tanlaydi va savat to'ldiradi**.

### Yuqori qism (karta)
- **Mijoz *** — qidiruv maydoni (nomi, telefon yoki kod bo'yicha). Natijadan tanlash kerak.
- **Narx turi *** — select (Chakana, Ulgurji va h.k.).
- **Yaratish** — forma yuboriladi (mijoz, narx turi, ombor, savatdagi mahsulotlar).

### Chap ustun — Tovarlar
- **Ombor *** — select. Tanlangandan keyin shu omborda qoldiq bor tovarlar kartochkalarda chiqadi.
- Tovarlar **kartochkalarda**: rasm (agar bor), nomi, narx (tanlangan narx turi bo'yicha). **Tovarga bosish** = savatga 1 dona qo'shiladi.
- Ombor tanlanmasa: "Omborni tanlang — shu ombordagi tovarlar ro'yxatda chiqadi."
- Omborda qoldiq yo'q bo'lsa: "Bu omborda qoldiq yo'q" xabari.

### O'ng ustun — Savat
- **Jadval:** Mahsulot | Miqdor (input) | Narx (input) | Summa | [O'chirish]
- Miqdor va narxni o'zgartirish mumkin; summa avtomatik hisoblanadi.
- Savat bo'sh bo'lsa: "Savat bo'sh. Omborni tanlang, tovarga bosing — savatga tushadi..."
- **Yaratish** bosilganda: mijoz tanlangan, ombor tanlangan va savatda kamida 1 mahsulot bo'lishi kerak; aks holda alert.

**Oqim:** Mijoz tanlash → Narx turi tanlash → Ombor tanlash → Tovarlarga bosib savat to'ldirish → Miqdor/narx tahrir → **Yaratish** → sotuv yaratiladi va **Tahrir sahifasiga** yo'naltiriladi.

---

## 3. Sotuv tahriri — `/sales/edit/{order_id}`

Sotuv bajarilguncha **qoralama**, keyin **Tasdiqlash** orqali **bajarilgan**.

### Chap qism
- **Orqaga** → `/sales`.
- **Hujjat raqami** (masalan S-00001).  
- **Holatga qarab tugmalar:**
  - **Qoralama:** **Tasdiqlash** (ombor qoldig'i kamayadi), admin uchun **O'chirish**.
  - **Bajarilgan:** faqat admin uchun **Tasdiqni bekor qilish** (qoldiq qaytadi).
- **Mijoz**, **Ombor**, **Narx turi**.
- **Mahsulotlar jadvali:** № | Mahsulot | Miqdor | Narx | Summa | (qoralama bo'lsa har bir qatorda O'chirish).
- **Jami:** jami summa.

### O'ng qism (faqat qoralama bo'lsa)
- **Mahsulot qo'shish:**
  - Mahsulot (select — nom va narx ko'rinadi).
  - Miqdor (input).
  - **Savatga qo'shish** tugmasi.
- **Savat** (vaqtinchalik):
  - Mahsulot | Miqdor | Summa | O'chirish.
  - **Barchasini buyurtmaga qo'shish** — savatdagi barcha qatorlar sotuvga qo'shiladi, keyin sahifa yangilanadi.

**Xatolik xabarlari:** Omborda yetarli mahsulot yo'q bo'lsa yoki tasdiqni bekor qilish qoidasi buzilsa — sahifa ustida alert ko'rsatiladi.

---

## Qisqacha

| Sahifa      | URL            | Vazifasi |
|------------|----------------|----------|
| Ro'yxat    | `/sales`       | Barcha sotuvlar, Yangi sotuv yaratish |
| Yangi sotuv| `/sales/new`   | Mijoz, narx turi, ombor, tovarlar (kartochkalar), savat, Yaratish |
| Tahrir     | `/sales/edit/{id}` | Mahsulotlar ro'yxati, qoralama bo'lsa qo'shish/savat, Tasdiqlash/O'chirish/Tasdiqni bekor qilish |

Sidebar da **Sotuvlar** havolasi `/sales` ga olib boradi.
