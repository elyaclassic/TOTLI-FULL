# Yetkazish kunini tanlash — dizayn hujjati

**Sana:** 2026-05-10
**Muallif:** Elyor + Claude (TOTLI BI senior arxitektor)
**Status:** APPROVED (foydalanuvchi tomonidan tasdiqlangan, implementation plan ga o'tish uchun tayyor)
**Jamoadan:** Nosir (Architect), Rustam (Backend), Diyor (Frontend), Anvar (DB), Sherzod (Security), Nodira (QA), Jahongir (DevOps), Bekzod (PM)

---

## 1. Maqsad

TOTLI BI dagi agent buyurtma flow'iga **belgilangan kun yetkazish** funksiyasini qo'shish. Hozirgi tizim "buyurtma tasdiqlandi = darhol yetkazildi" deb hisoblaydi. Yangi flow: buyurtma bugun tasdiqlanib, **boshqa kun** yuklanishi va yetkazilishi mumkin.

Shu bilan birga, audit topgan 4 ta kamchilik (B, A, D, E) atomik tuzatiladi.

## 2. Muammo

### 2.1 Hozirgi flow kamchiligi

Hozirda:
- Agent buyurtma yaratadi (`draft`)
- Supervisor `confirm` bosadi → bir vaqtning o'zida quyidagilar sodir bo'ladi:
  - Stock kamayadi
  - Production trigger qilinadi (kerak bo'lsa)
  - `partner.balance += debt`
  - Driver auto-assign (birinchi faol)
  - Delivery yaratiladi
  - Status `confirmed`/`completed` ga o'tadi

Bu real biznesga mos kelmaydi:
- **Yetkazish ertasi yoki keyingi kunlarda bo'lishi mumkin**
- Driver bir kun ko'p, bir kun kam orderlar oladi (xaotik ro'yxat)
- Mahsulot omborda turibdi, lekin mijoz hisobiga qarz allaqachon yozilgan
- Agar haydovchi yetkazib bormasa ham qarz qoladi (revert qiyin)

### 2.2 Audit kamchiliklari

| # | Kamchilik | Joylashuv |
|---|-----------|-----------|
| **B** | Revert da `partner.balance` qaytarilmaydi | `app/routes/sales.py:752-784` |
| **A** | Stock 2x deduct ehtimoli (waiting → confirmed transition) | `sales.py:570`, `agent_order_service.py:55` |
| **D** | Driver birinchi faol bo'lsa avtomatik tayinlanadi (yangi flow'da kerak emas) | `agent_order_service.py:66-75` |
| **E** | Waiting_production orderlar uchun supervisor dashboard yo'q | yangi route kerak |

## 3. Yechim — yangi status oqimi

### 3.1 Status flow

```
draft (Yangi)
   │
   │ supervisor "Tasdiqlash" tugmasini bosadi
   │ → faqat status o'zgaradi, hech narsa boshqa qilinmaydi
   ▼
confirmed (Tayyor)
   │
   │ supervisor "Yuklash" tugmasini bosadi
   │ → modal: delivery_date + driver_id kiritadi
   │ → stock check
   │
   ├──[stok yetarli]──▶  out_for_delivery (Yo'lda)
   │                       - stock_movement (-)
   │                       - delivery yaratiladi (driver_id, scheduled_date)
   │                       - dispatched_at = NOW
   │                       - driver mobile'da ko'rinadi
   │                       │
   │                       │ driver mobile'da "Yetkazdim" tasdiqlaydi
   │                       ▼
   │                     delivered (Yetkazildi)
   │                       - partner.balance += debt
   │                       - delivery.status = 'delivered'
   │
   └──[stok yetmasa]──▶  waiting_production (Production kutilmoqda)
                          - production_order yaratiladi
                          - delivery_date saqlanadi
                          - production tugagach: avtomatik out_for_delivery ga
```

Har holatda → `cancelled` (Bekor) — admin/manager tomonidan.

### 3.2 Status nomlari (DB ↔ UI)

| DB qiymat | UI o'zbekcha |
|-----------|--------------|
| `draft` | Yangi |
| `confirmed` | Tayyor |
| `waiting_production` | Production kutilmoqda |
| `out_for_delivery` | Yo'lda |
| `delivered` | Yetkazildi |
| `cancelled` | Bekor |

## 4. Database o'zgarishi

### 4.1 Yangi ustunlar (additive)

```sql
ALTER TABLE orders ADD COLUMN delivery_date DATE NULL;
ALTER TABLE orders ADD COLUMN dispatched_at TIMESTAMP NULL;
```

`dispatched_at` — supervisor "Yuklash" bosgan vaqt (audit izi).

### 4.2 Status enum kengayishi

`status` ustun hozir STRING(20). Yangi qiymatlar qo'shiladi (kod tarafidan validatsiya):

```python
ORDER_STATUSES = (
    'draft', 'confirmed', 'waiting_production',
    'out_for_delivery', 'delivered', 'cancelled'
)
```

Eski `completed` qiymati `delivered` ga semantik almashinadi (migratsiya skripti).

### 4.3 Indekslar

```sql
CREATE INDEX idx_orders_delivery_date_status ON orders(delivery_date, status)
  WHERE status = 'out_for_delivery';

CREATE INDEX idx_orders_status_dispatched ON orders(status, dispatched_at)
  WHERE status IN ('confirmed', 'waiting_production');
```

## 5. Komponent o'zgarishlari

### 5.1 Backend — `app/routes/sales.py`

#### 5.1.1 `POST /sales/{order_id}/confirm` — soddalashadi

**Hozirgi:** stock −, balance +=debt, production trigger, status=completed
**Yangi:** faqat status='draft' → 'confirmed' atomik UPDATE. Hech narsa qilmaydi.

```python
# Atomik UPDATE — double-confirm xavfini oldini olish
result = db.execute(
    text("UPDATE orders SET status='confirmed' WHERE id=:id AND status='draft'"),
    {"id": order_id}
)
if result.rowcount == 0:
    raise HTTPException(409, "Order allaqachon tasdiqlangan yoki status mos kelmaydi")
```

#### 5.1.2 `POST /sales/{order_id}/dispatch` — YANGI endpoint

```
Body: {"delivery_date": "2026-05-12", "driver_id": 5}

Validatsiya:
  - delivery_date >= today (kelajak yoki bugun)
  - driver_id mavjud va active=true
  - order.status == 'confirmed' (atomik check)

Mantiq:
  1. order.pending_driver_id = driver_id (Driver tayinlanadi)
  2. order.delivery_date = delivery_date
  3. order.dispatched_at = NOW
  4. Stock check har order_item uchun:
     - warehouse_id = order_item.warehouse_id (agar NULL bo'lsa, order.warehouse_id)
     - Hozirgi `_warehouse_id_for_ingredient` mantiqi qayta ishlatiladi
  5. Atomik UPDATE: status='confirmed' → 'out_for_delivery' yoki 'waiting_production'
  6. Yetarli bo'lsa:
     - StockMovement (-) yaratiladi (har item uchun, document_type='Sale')
     - Delivery yaratiladi (driver_id, scheduled_date=delivery_date, status='pending')
     - status = 'out_for_delivery'
  7. Yetmasa:
     - Production order yaratiladi (kerakli yarim tayyor + xom ashyo)
     - status = 'waiting_production'
     - Telegram: qiyom/qadoqlovchiga: "AGT-X yetkazib berish uchun yetishmayotgan mahsulotlar..."
     - delivery_date va pending_driver_id order'da saqlanadi (try_confirm_waiting_orders ishlatadi)
```

#### 5.1.3 `POST /sales/{order_id}/revert` — bug fix B

```python
# Faqat 'delivered' bo'lgan orderda balance qaytarish kerak
if order.status == 'delivered':
    if order.previous_partner_balance is not None and order.partner_id:
        partner.balance = order.previous_partner_balance
    # Delivery'ni 'cancelled' ga
    delivery = db.query(Delivery).filter_by(order_id=order.id).first()
    if delivery:
        delivery.status = 'cancelled'

# Boshqa statuslarda balance hech yozilmagan, qaytarish kerak emas
# Stock'ni qaytarish (out_for_delivery, delivered):
if order.status in ('out_for_delivery', 'delivered'):
    for movement in stock_movements_of(order):
        # Teskari movement yarat (epsilon_clean_qty bilan)
        ...

order.status = 'cancelled'
```

### 5.2 Driver-related — `app/services/agent_order_service.py`

#### 5.2.1 `try_confirm_waiting_orders()` — yangilash

Production tugagach trigger bo'ladi:

```python
# Hozirgi: waiting_production → confirmed (stock deduct + delivery + balance)
# Yangi: waiting_production → out_for_delivery (stock deduct + delivery)
# Balance esa driver yetkazib tasdiqlaganda yoziladi (yangi /api/driver/deliver endpoint)

# Pre-condition: order.pending_driver_id va order.delivery_date /dispatch paytida o'rnatilgan
# Agar pending_driver_id NULL bo'lsa, supervisor'ga warning Telegram, status waiting_production qoladi

# Atomik check:
if not order.pending_driver_id:
    notify_supervisor(f"PR uchun haydovchi tanlanmagan: {order.number}")
    continue  # supervisor qo'lda /dispatch ni qayta bajarishi kerak

result = db.execute(
    text("""UPDATE orders SET status='out_for_delivery'
            WHERE id=:id AND status='waiting_production'"""),
    {"id": order.id}
)
if result.rowcount == 1:
    apply_sale_stock_deduction(order)
    create_delivery(order, driver_id=order.pending_driver_id, scheduled_date=order.delivery_date)
```

#### 5.2.2 `_assign_default_driver()` — bug fix D

**OLIB TASHLANADI.** Yangi flow'da driver supervisor tomonidan qo'lda tanlanadi.

### 5.3 Driver mobile API — `app/routes/api_driver_*.py`

#### 5.3.1 `GET /api/driver/orders` — filter yangilanadi

```python
# Hozirgi: driver_id bo'yicha barcha orderlarni qaytaradi
# Yangi: faqat status='out_for_delivery' va delivery_date <= bugun
```

#### 5.3.2 `POST /api/driver/order/{id}/deliver` — YANGI endpoint

```python
# Driver yetkazganda chaqiriladi
# Atomik UPDATE: status='out_for_delivery' → 'delivered'
# partner.balance += order.debt
# delivery.status = 'delivered', delivery.completed_at = NOW
```

### 5.4 Supervisor web

#### 5.4.1 `/sales` — sales list yangilanadi

- Yangi ustun: "Yuklash sanasi" (`delivery_date`)
- Yangi ustun: "Status" — Yangi/Tayyor/Yo'lda/Yetkazildi/Bekor
- Yangi tugma har order yonida: "Yuklash" (faqat `confirmed` status uchun)
- Yangi tablar yuqorida: "Yangi (10) | Tayyor (15) | Yo'lda (8) | ..."

#### 5.4.2 `/sales/{order_id}/dispatch-modal` — yangi template

```html
<!-- Modal: Yuklash sanasi va haydovchi tanlash -->
<form action="/sales/{order_id}/dispatch" method="POST">
  <label>Yuklash sanasi:</label>
  <input type="date" name="delivery_date" min="{bugun}" required>
  
  <label>Haydovchi:</label>
  <select name="driver_id" required>
    {% for d in active_drivers %}
      <option value="{{ d.id }}">{{ d.full_name }}</option>
    {% endfor %}
  </select>
  
  <button type="submit">Yo'lga chiqarish</button>
</form>
```

#### 5.4.3 `/sales/deliveries` — YANGI sahifa (kamchilik E)

```
Tablar:
  - Bugun (delivery_date = today, status='out_for_delivery')
  - Ertaga (delivery_date = today+1)
  - Kechikkanlar (delivery_date < today, status != 'delivered')
  - Production kutilmoqda (status='waiting_production')

Har row: order_no, mijoz, driver, delivery_date, total
```

## 6. Migratsiya

### 6.1 Skript — `scripts/migrate_orders_to_new_status_20260510.py`

```
Bosqich 1: --dry-run (default)
  Mavjud orderlarni status guruhlab ko'rsatadi:
    - count(status='completed')           → delivered ga ko'chiriladi
    - count(status='confirmed', delivery=delivered) → delivered
    - count(status='confirmed', delivery=pending)   → out_for_delivery
    - count(status='confirmed', delivery=NULL)      → SO'RAYDI har birini
    - count(status='draft', 'waiting_production')   → o'zgarmaydi

Bosqich 2: --apply
  Backup yaratadi (DB + git tag)
  UPDATE'lar ijro etadi
  Tasdiq: integrity check + smoke test
```

### 6.2 ORM model

`app/models/database.py:Order` modelida statuslarni dokumentatsiya bilan kengaytirish:

```python
# orders.status valid values:
#   'draft', 'confirmed', 'waiting_production',
#   'out_for_delivery', 'delivered', 'cancelled'
```

## 7. Rollback rejasi

```
Agar deploy'dan keyin biron bug topilsa:
  1. Status migratsiya teskari skripti: scripts/rollback_status_20260510.py
     - 'delivered' → 'completed'
     - 'out_for_delivery' → 'confirmed' (delivery_date saqlanadi, ahamiyatsiz)
     - 'cancelled' → asl status (audit'dan)
  2. Yangi endpointlarni o'chirish: /dispatch, /deliver
  3. Driver mobile filter rollback (har orderni ko'rsatish)
  4. Sales template eski versiya
```

Backup: deploy oldin git tag `pre-delivery-scheduling-2026-05-10` + DB snapshot.

## 8. Testlash strategiyasi

### 8.1 Unit testlar (yangi)

- `test_dispatch_endpoint`: stock yetarli/yetmagan holatlarda
- `test_deliver_endpoint`: balance += debt, faqat bir marta (idempotency)
- `test_revert_balance`: faqat 'delivered' status revert da balance qaytariladi
- `test_atomic_confirm`: 2 ta parallel `/confirm` so'rovi → faqat bittasi muvaffaqiyatli

### 8.2 Smoke test (manual, deploy posti)

1. Yangi order yaratish → status='draft'
2. Supervisor tasdiqlash → status='confirmed', stock o'zgarmaydi
3. Supervisor "Yuklash" → modal → sana+driver → status='out_for_delivery', stock −
4. Driver mobile → orderni ko'radi → "Yetkazdim" → status='delivered', balance +=
5. Revert delivered → status='cancelled', balance -=

### 8.3 Edge case'lar

- **Concurrent:** 2 ta supervisor bir vaqtda "Yuklash" bosadi → atomik UPDATE bilan faqat birinchi muvaffaqiyatli, ikkinchi 409 oladi
- **Cancel out_for_delivery:** stock qaytariladi (teskari movement), Delivery 'cancelled', driver mobile'dan yo'qoladi
- **Cancel delivered:** balance qaytariladi (B fix), stock qaytariladi
- **Production:** 'waiting_production' dan auto-confirm bo'lganda balance hali yozilmaydi (faqat driver yetkazganda)
- **Past sana:** delivery_date=kecha — qabul qilinadi (kechikkan orderlar uchun, "Kechikkan" tabida ko'rsatiladi)
- **Driver tanlanmagan production:** auto-confirm waiting_production'da pending_driver_id NULL bo'lsa, status 'waiting_production' da qoladi va supervisor'ga Telegram alert yuboriladi
- **Driver "Yetkazdim" 2 marta:** atomik UPDATE WHERE status='out_for_delivery' bilan idempotent (ikkinchi so'rov 409 oladi)
- **Sales/edit:** order_items'ni o'zgartirish faqat status IN ('draft', 'confirmed') ga ruxsat etiladi. 'out_for_delivery' va keyingilarda RAD ETILADI

## 9. Deploy bosqichi (Tier C — yakshanba kechasi)

```
00:00 — Backup yaratish (git tag + DB snapshot + offsite)
00:05 — Migratsiya skripti --dry-run
00:10 — Migratsiya skripti --apply (foydalanuvchi tasdig'i)
00:15 — Yangi kodni deploy (taskkill + start.bat)
00:20 — Smoke test (manual 5 daqiqa)
00:25 — Telegram bildirish: "deploy tugadi"
00:30 — Tinch monitor (1 soat)
01:30 — Agar OK bo'lsa, restart watchdog yoqiladi
```

Rollback chegarasi: 30 daqiqa ichida 5+ ta xato → rollback skript.

## 10. Open savol

Yo'q — barcha asosiy savollar foydalanuvchi tomonidan javoblangan:

1. ✅ Status nomi: o'zbek (Yangi/Tayyor/Yo'lda/Yetkazildi/Bekor)
2. ✅ Stock vaqti: yuklash sanasi belgilanganda
3. ✅ Migratsiya: avval ro'yxat, qo'lda hal qilish
4. ✅ Driver: supervisor qo'lda tanlaydi (auto-assign olib tashlanadi)
5. ✅ Balance: faqat driver yetkazib tasdiqlaganda yoziladi

## 11. Bog'liq fayllar

### O'zgartiriladigan
- `app/routes/sales.py` — confirm soddalashadi, dispatch yangi, revert kengayadi
- `app/routes/api_agent_ops.py` — agent endpoint'lari (minimal)
- `app/routes/api_driver_*.py` — driver mobile filter va deliver endpoint
- `app/services/agent_order_service.py` — auto-confirm yangilanadi, default_driver olib tashlanadi
- `app/services/stock_service.py` — atomik checklar
- `app/templates/sales/list.html` — yangi ustun, yangi tugma
- `app/templates/sales/dispatch_modal.html` — YANGI
- `app/templates/sales/deliveries.html` — YANGI
- `app/models/database.py` — Order modelida status docstring
- `app/middleware.py` — yangi endpointlarni whitelist (CSRF + auth)

### Yangi yaratiladigan
- `scripts/migrate_orders_to_new_status_20260510.py`
- `scripts/rollback_status_20260510.py`
- `tests/test_dispatch_flow.py`
- `tests/test_revert_balance.py`

### Migratsiya
- `alembic/versions/XXXXXX_add_delivery_date_dispatched_at.py`
- 2 ta yangi index

---

## Tasdiq

**Foydalanuvchi qarori (2026-05-10):** dizayn tasdiqlangan, design hujjati yozish va keyingi bosqich (writing-plans) ga o'tish so'ralgan.
