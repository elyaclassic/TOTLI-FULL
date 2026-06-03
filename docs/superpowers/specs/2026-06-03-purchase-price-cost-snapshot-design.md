# Tan narx (purchase_price) corruption fix — Dizayn (2026-06-03)

## Muammo

`Product.purchase_price` (tan narx) bir nechta joyda **qo'riqsiz qayta yoziladi** va buziladi:
- `production.py:294` (`_update_output_cost_and_price`): har production yakunda flat = shu partiyaning dona-material narxi. G'ayritabiiy partiya (xato material narxi) → buzilish (KITOB 62k→464k).
- `qoldiqlar.py:1798`: QLD/INV hujjatda `item.cost_price>0` bo'lsa qayta yozadi.
- `reports.py:1193`: stock-source hisobot ham qayta yozadi (hisobot ma'lumotni mutatsiya qiladi).

Foyda hisoboti (`reports.py:2544`, `2605`): `COGS = Product.purchase_price × sotilgan_miqdor`, **JORIY** narxni ishlatadi → narx o'zgarsa **barcha o'tmish sotuvlari foydasi qayta hisoblanadi** (KITOB 464k → butun tarix yolg'on zarar).

Ikki qatlamli muammo: **volatillik** (1 partiya buzadi) + **retroaktivlik** (joriy narx tarixga ta'sir qiladi).

## Qarorlar (foydalanuvchi tasdiqlagan)
1. Foyda **sotuv vaqtidagi** tan narxni ishlatadi (snapshot, qotiriladi).
2. Production tan narxni **oxirgi narx + anomaliya qo'riq** bilan yangilaydi.
3. Eski orderlar **tuzatilgan joriy narxga fallback** qiladi.

## Yechim (5 qism)

### 1. OrderItem cost snapshot
- `OrderItem`'ga yangi ustun: `cost_price = Column(Float, default=0)` (ORM + `ensure_*_column` migratsiya, birga — schema drift oldini olish).
- OrderItem **yaratilganda** `cost_price` = joriy `Product.purchase_price`. Joylar (barcha sotuv item yaratish nuqtalari):
  - `api_agent_ops.py` (agent order create, exchange child/return items)
  - `sales.py` (POS/web sale create, exchange edit `_apply_exchange_edit`)
  - boshqa OrderItem yaratuvchi joylar (grep `OrderItem(` bilan topiladi)
- Helper: `snapshot_item_cost(db, order_item)` yoki yaratishda inline `cost_price=prod.purchase_price`.
- Bir marta yoziladi; keyin o'zgarmaydi (driver qty kamaytirsa cost_price o'zgarmaydi, faqat quantity).

### 2. Foyda snapshot'ni ishlatadi
- `reports.py` foyda hisoblovchi joylar (`_profit_*`, line ~2544, ~2605):
  `cost = float(oi.cost_price or 0) or float(prod.purchase_price or 0)` — snapshot bo'lsa shu, aks holda fallback.
- Boshqa COGS/tannarx ishlatuvchi hisobotlar ham shu pattern (agar foyda ko'rsatsa).

### 3. Production tan narx — oxirgi + anomaliya qo'riq
- `_update_output_cost_and_price` (production.py:279): `cost` (yangi) anomaliya bo'lsa **yozmaydi**:
  - `cost > output_product.sale_price` (sotuvdan baland — allaqachon warn bor) **YOKI**
  - `old_price > 0 and cost > 3 * old_price` (eski narxdan 3 baravar oshган)
  → eski `purchase_price` saqlanadi + `logger.warning` (PRICE ANOMALY SKIPPED). `product_price_history`'ga **yozmaydi** (o'zgarish bo'lmadi).
  - Aks holda hozirgidek yangilaydi.

### 4. Soxta qayta-yozishlarni olib tashlash
- `qoldiqlar.py:1795-1798`: `prod.purchase_price = item.cost_price` blokini **o'chirish** (QLD/INV qoldiq kiritish tan narx hodisasi emas; Stock.cost_price'ga tegish mumkin, lekin Product.purchase_price'ga emas).
- `reports.py:1193`: `product.purchase_price = tannarx` mutatsiyasini **o'chirish** (hisobot read-only bo'lishi kerak).

### 5. Data cleanup (buzilgan narxlarni tuzatish)
- Diagnostika skript (`C:\tools\`): `purchase_price` anomaliyalari (`purchase_price > sale_price` yoki `purchase_price > 3× median(price_history)`).
- Har biri uchun `product_price_history`'dan oxirgi **normal** (anomaliya bo'lmagan) `new_purchase_price`'ni topib tiklash. Topilmasa — ro'yxatga (admin qo'lda).
- DRY-RUN → ko'rib chiqish → `--apply` (backup bilan).
- Keyin eski orderlar fallback orqali tuzatilgan narxni ishlatadi.

## Komponentlar va chegaralar
- **Model:** `OrderItem.cost_price` (snapshot maydoni).
- **Snapshot:** OrderItem yaratish nuqtalari (inline yoki helper).
- **Foyda:** `reports.py` COGS — snapshot + fallback.
- **Production guard:** `_update_output_cost_and_price` (izolyatsiyalangan funksiya — oson test).
- **Cleanup:** alohida skript (kod emas, bir martalik data).

## Test rejasi
- `OrderItem.cost_price` migratsiya: ustun yaratiladi.
- Snapshot: order yaratilganda cost_price = purchase_price.
- Foyda: cost_price>0 → shu ishlatiladi; cost_price=0 → fallback purchase_price.
- Anomaliya qo'riq: `cost > sale_price` → purchase_price o'zgarmaydi; `cost > 3×old` → o'zgarmaydi; normal → yangilanadi.
- Soxta overwrite: QLD confirm purchase_price'ni o'zgartirmaydi.

## Xavf va ehtiyot
- Deploy oldidan DB backup. Restart kerak.
- `ensure_*_column` pending tranzaksiya orasida chaqirilmasin.
- Snapshot faqat YANGI orderlarga; eski orderlar fallback (cleanup'dan keyin to'g'ri).
- Cleanup ehtiyotkor: anomaliya aniqlash + price_history'dan tiklash, qo'lda ko'rib chiqish.

## Bog'liq
- [[project-purchase-price-corruption]] (KITOB 62k→464k incident).
- [[project-audit-findings-20260603]] (C2 topilma).
