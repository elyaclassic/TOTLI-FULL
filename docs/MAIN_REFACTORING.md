# main.py ni qisqartirish — maslahat va reja

**Hozirgi holat:** `main.py` ~14 000+ qator, 340+ ta route. Kodni modullarga bo‘lish orqali qisqartirish mumkin.

---

## 1. Routerlarni ulash (tez natija)

`app/routes/` da allaqachon mavjud fayllar: `sales.py`, `qoldiqlar.py`, `purchases.py`, `finance.py`, `production.py`, `warehouse.py`, `employees.py`, `partners.py`, `products.py` va boshqalar. **Lekin** ularning ko‘pchiligi `main.py` da `include_router` orqali ulangan emas — route’lar hali ham `main.py` ichida.

**Qilish:**
- `main.py` dagi route’larni mavjud router fayllariga **ko‘chirish** (masalan, `/sales/pos`, `/sales/...` → `app/routes/sales.py`).
- Har bir routerni `main.py` da ulash:
  ```python
  from app.routes import sales as sales_routes
  app.include_router(sales_routes.router)
  ```
- Bunda `main.py` dan yuzlab qatorlar ketadi, route’lar o‘z modullarida qoladi.

---

## 2. Yordamchi funksiyalarni alohida modulga chiqarish

`main.py` ichida umumiy ishlatiladigan funksiyalar bor, masalan:
- `create_stock_movement`
- `delete_stock_movements_for_document`
- `_get_sales_warehouse`, `_get_pos_warehouse_for_user`, `_get_pos_price_type`
- `get_product_cost_for_sale`, `get_product_sale_price_for_pos`

**Qilish:**
- `app/services/stock_service.py` (yoki `app/utils/stock.py`) yarating.
- `create_stock_movement`, `delete_stock_movements_for_document` ni shu yerga ko‘chiring.
- `app/services/pos_helpers.py` (yoki `app/utils/pos_helpers.py`) — POS va savdo uchun `_get_sales_warehouse`, `_get_pos_warehouse_for_user`, narx/ombor bo‘yicha funksiyalarni shu yerga yig‘ing.
- `main.py` va route fayllarida: `from app.services.stock_service import create_stock_movement, delete_stock_movements_for_document` kabi import qiling.

Natija: `main.py` dan yana 200–400 qator kamayadi, mantiq bitta joyda bo‘ladi.

---

## 3. Route guruhlarini bo‘lish (qaysi narsa qayerga)

Quyidagi prefix’lar bo‘yicha route’larni tegishli routerga ko‘chirish ma’qul:

| Prefix / mavzu        | Fayl (mavjud yoki yangi)   | Taxminiy qatorlar |
|----------------------|----------------------------|--------------------|
| `/sales` (pos, list, edit, revert, return) | `app/routes/sales.py`       | 500+ → sales.py   |
| `/qoldiqlar/tovar`, `/qoldiqlar/kassa`, `/qoldiqlar/kontragent` | `app/routes/qoldiqlar.py`   | 400+ → qoldiqlar.py |
| `/purchases`         | `app/routes/purchases.py`  | 300+ → purchases.py |
| `/finance`           | `app/routes/finance.py`    | 400+ → finance.py |
| `/production`        | `app/routes/production.py` | 400+ → production.py |
| `/warehouse`         | `app/routes/warehouse.py`  | 200+ → warehouse.py |
| `/products`          | `app/routes/products.py`  | 200+ → products.py |
| `/employees`         | `app/routes/employees.py`  | 300+ → employees.py |
| `/info` (units, categories, price-types, prices, departments, users) | `app/routes/info.py` (yoki alohida info_*.py) | 500+ → info.py |
| `/dashboard`         | `app/routes/dashboard.py`  | 600+ → dashboard.py |

Birinchi navbatda bitta katta blokni (masalan, `/sales` yoki `/qoldiqlar/tovar`) to‘liq routerga ko‘chirib, ishlashini tekshirish eng xavfsiz.

---

## 4. main.py da nima qolishi kerak

Qisqartirilgan `main.py` da ma’qul tarkib:
- Import’lar (FastAPI, middleware, router’lar).
- `app = FastAPI(...)`, `app.mount("/static", ...)`.
- Middleware’lar (CSRF, auth, 404/500).
- Barcha `app.include_router(...)` chaqiruvlari.
- Agar kerak bo‘lsa — 1–2 ta global route (masalan, `/`, `/ping`, `/favicon.ico`).
- `if __name__ == "__main__": uvicorn.run(...)`.

Umumiy maqsad: **main.py 300–500 qator atrofida** qolsin, qolgani router va service modullarida bo‘lsin.

---

## 5. Bosqichma-bosqich tartib

1. **Yordamchi funksiyalarni chiqarish**  
   `create_stock_movement`, `delete_stock_movements_for_document` → `app/services/stock_service.py`. Import’larni yangilang va test qiling.

2. **Bitta katta blokni ko‘chirish**  
   Masalan, `/sales/pos` va barcha `/sales/*` route’lari `main.py` dan `app/routes/sales.py` ga. Router allaqachon bor bo‘lsa, faqat endpoint’larni ko‘chiring va `main.py` da `include_router(sales_routes.router)` qiling.

3. **Qolgan bloklarni ketma-ket ko‘chirish**  
   Keyingi navbatda: qoldiqlar (tovar/kassa/kontragent), purchases, finance, production, warehouse, products, employees, info, dashboard.

4. **Har bir bosqichdan keyin**  
   Serverni ishga tushirib, muhim sahifalarni tekshirish (login, sotuv, qoldiq, kirim, hisobotlar).

---

## 6. Qisqa xulosa

| Harakat | Natija |
|--------|--------|
| Router’larni ulash va route’larni ko‘chirish | main.py 10 000+ qatorga qisqaradi |
| Yordamchi funksiyalarni `app/services/` ga chiqarish | main.py yanada soddalashadi, kod qayta ishlatiladi |
| main.py da faqat app, middleware, include_router | Bitta fayl 300–500 qator atrofida qoladi |

Agar xohlasangiz, keyingi qadamda bitta konkret blok (masalan, faqat `create_stock_movement` + `delete_stock_movements_for_document` yoki faqat `/sales/pos` bloki) uchun aniq patch/namuna yozib berish mumkin.
