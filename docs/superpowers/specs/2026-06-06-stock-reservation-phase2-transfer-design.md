# Stock Reservation Faza 2-A: Transfer band himoyasi — Dizayn

**Sana:** 2026-06-06
**Holat:** Tasdiqlangan dizayn → plan
**Bog'liq:** [[project-stock-reservation-deployed-20260606]] (Faza 1), order 569 incident

---

## 1. Muammo

Faza 1 reservation faqat **sotuv/dispatch** darvozalarini qamradi. Ishlab chiqarilgan tayyor mahsulot agent buyurtmasiga band qilingan bo'lsa ham, **ombordan omborga o'tkazish (transfer)** yoki **konversiya** uni olib ketishi mumkin → band qilingan mahsulot do'konga ketib, agent buyurtmasini bo'sh qoldiradi (order 569 holati: PR mahsuloti wh3 ga tushgan, keyin OT bilan do'konlarga o'tkazilib, agent buyurtma kuttirgan).

## 2. Maqsad

Band qilingan (waiting_production buyurtmalar tomonidan) mahsulotni transfer yoki konversiya **qattiq bloklasin** (Faza 1 sotuv bilan izchil). Manager xato xabarida band miqdorni ko'rsin. Admin override va reservation UI alohida bo'laklar (B, C) — bu spec'dan tashqarida.

**Qabul qilingan qarorlar (foydalanuvchi 2026-06-06):**
- Birinchi Faza 2 bo'lagi = **A (transfer himoyasi)**.
- Xatti-harakat = **qattiq bloklash** (Faza 1 kabi). Admin override = keyingi bo'lak (B).
- Doira = transfer + konversiya.

## 3. Yondashuv

Faza 1 ning `get_reserved_quantity(db, warehouse_id, product_id)` helperini (`app/services/stock_reservation.py`) shu 3 darvozada qayta ishlatish. Transfer/konversiya = order'siz iste'molchi → `before_order=None` (barcha waiting band ayriladi). Yangi mantiq YO'Q.

## 4. Call-site o'zgarishlari

| Fayl:qator | Funksiya | Hozir | Tuzatilgan |
|------------|----------|-------|-----------|
| `warehouse.py:~655` | transfer confirm | `have = get_stock_at_date(db, from_wh, pid, cutoff)` | `have = get_stock_at_date(...) - get_reserved_quantity(db, from_wh, pid)` |
| `warehouse.py:~827` | to'g'ridan movement | `have_q = source.quantity` | `have_q = float(source.quantity or 0) - get_reserved_quantity(db, from_wh, pid)` |
| `production_convert.py:~209` | konversiya manba (lock saqlanadi) | `have = source_stock.quantity` | `have = float(source_stock.quantity or 0) - get_reserved_quantity(db, src_wh, src_pid)` |

Import: har faylga `from app.services.stock_reservation import get_reserved_quantity` (agar yo'q bo'lsa).

## 5. Xato xabari

Band > 0 bo'lganda xato xabariga band miqdorni qo'shish, masalan:
`«{name}» yetarli emas (kerak: {need}, mavjud: {avail}, shundan {reserved} band — waiting buyurtmalar)`.
Band = 0 bo'lsa eski xabar formati (o'zgarishsiz).

## 6. Edge case va to'g'rilik

- **Band = 0** (waiting buyurtma yo'q) → `get_reserved_quantity` 0 qaytaradi → xulq o'zgarmaydi.
- **Back-dated transfer** (warehouse.py:655 cutoff o'tgan sana): joriy band ayriladi (konservativ — band qilingan mahsulot ketmasligi muhim). Kam uchraydi.
- **production_convert `.with_for_update()` lock SAQLANADI** — band alohida read-only sub-query, lock'ga ta'sir qilmaydi.
- **Manfiy `have`** (band > jismoniy) → `have + 1e-6 < need` rad etadi (to'g'ri).
- **Epsilon** (`+ 1e-6`) mavjud taqqoslashlar saqlanadi.

## 7. Test strategiyasi

- `tests/test_reservation_transfer.py` (yangi):
  - waiting buyurtma band qilgan mahsulotni transfer qilish bloklanadi (have − reserved < need).
  - band 0 bo'lsa transfer o'tadi.
  - konversiya: band manba mahsulotni bloklaydi.
- Service-level (`get_reserved_quantity` mavjud unit-tested); gate logikasi sodda taqqoslash.
- Regressiya: `tests/test_warehouse*.py` (mavjud bo'lsa) o'zgarmasin.

## 8. Doiradan tashqari (keyingi bo'laklar)

- **B — Admin override:** bloklangan transfer/POS'ni admin "baribir o'tkaz" qila olsin.
- **C — Reservation UI:** qoldiq hisoboti + dispatch ekranida "Jismoniy / Band / Erkin" ko'rsatish.

## 9. Risk

- **Ma'lumotga ta'sir:** Yo'q (band saqlanmaydi, o'qish-vaqti hisoblash).
- **Xulq o'zgarishi:** manager transferi band mahsulotda bloklanishi mumkin — maqsadli. Override yo'qligi (B kelguncha) manager'ni band mahsulot uchun kuttirishi mumkin; xato xabari sababni tushuntiradi. Deploy paytida 0 waiting bo'lsa darhol ta'sir yo'q (Faza 1 kabi).
- **Deploy:** restart kerak (kod). Tier B.
