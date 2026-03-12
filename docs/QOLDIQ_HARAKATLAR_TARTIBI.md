# Qoldiq harakatlari tartibi va operatsiyalar tekshiruvi

## Jadval tartibi (Qoldiq manbai hisoboti)

- **Birinchi qator** — birinchi harakat (masalan qoldiq tushuriladi yoki kirim).
- **Oxirgi qator** — eng so'nggi harakat.
- «Qoldiq (harakatdan keyin)» — shu qatordagi harakatdan keyingi yig'indi qoldiq.

Texnik: `reports/stock/source` da harakatlar `created_at` o'sish bo'yicha olinadi, qatorlar sana bo'yicha tartiblanadi, yig'indi shu tartibda hisoblanadi.

---

## Operatsiyalar mantiqi (tasdiqlangan)

### 1. Qoldiq tuzatish (StockAdjustmentDoc / QLD)
- Tanlangan ombor + mahsulot uchun qoldiq **o'sadi** yoki kamayadi (item.quantity, item.warehouse_id).
- `create_stock_movement(warehouse_id=item.warehouse_id, quantity_change=...)`.

### 2. Tovar kirimi (Purchase)
- **Qaysi ombor tanlangan bo'lsa (purchase.warehouse_id), o'sha omborga kiritiladi** — qoldiq ko'payadi.
- `create_stock_movement(warehouse_id=purchase.warehouse_id, quantity_change=item.quantity)`.
- Manba: `main.py` — purchase tasdiqlash (kirim confirm).

### 3. Ombordan omborga (WarehouseTransfer)
- **Qayerdan (from_warehouse_id):** qoldiq **kamayadi** (`quantity_change=-item.quantity`).
- **Qayerga (to_warehouse_id):** qoldiq **ko'payadi** (`quantity_change=item.quantity`).
- Tasdiqlashdan oldin «qayerdan» omborda bitta mahsulot uchun bir nechta Stock qatori bo'lsa, ular yig'indiga birlashtiriladi, keyin tekshiruv va chiqim bajariladi.

### 4. Ishlab chiqarish (Production)
- **Qaysi ombordan (production.warehouse_id — xom ashyo):** materiallar **kamayadi** (`quantity_change=-required`).
- **Qayerga (output_warehouse_id yoki warehouse_id):** tayyor/yarim tayyor mahsulot **qo'shiladi** (`quantity_change=output_units`).

### 5. Sotuv (Sale)
- **Buyurtmadagi ombor (order.warehouse_id):** qoldiq **kamayadi** (`quantity_change=-item.quantity`).

---

## Xulosa

- Jadvalda tartib: birinchi qator = birinchi harakat, oxirgi = eng so'nggi; barcha operatsiyalar yuqoridagi mantiqda to'g'ri ishlaydi.
- Agar tasdiqlangan hujjatlarni bekor qilib qayta tasdiqlasangiz, yana shu tartib va qoidalar qo'llanadi.
