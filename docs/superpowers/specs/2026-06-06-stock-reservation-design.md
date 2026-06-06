# Stock Reservation (waiting_production band qilish) — Dizayn

**Sana:** 2026-06-06
**Holat:** Tasdiqlangan dizayn → plan tuziladi
**Bog'liq:** [[project-stock-report-asof-fix-20260606]], order 559 (AGT-20260604-006) starvation incident

---

## 1. Muammo

`waiting_production` statusdagi agent buyurtmasi bir nechta ishlab chiqarilayotgan mahsulotni kutganda **starvation** (ochlikdan qolish) yuz beradi:

- Buyurtma ko'p item kutadi (masalan KESHULIK + MAYDA PISTA).
- Production'lar **birma-bir** tugaydi, har biri stockni umumiy hovuzga qo'shadi.
- Oxirgi item tayyor bo'lguncha, avval tayyor bo'lganlarini **boshqa buyurtmalar yeb ketadi**.
- Natija: buyurtma "barcha item bir vaqtda yetarli" holatiga hech qachon yetmaydi → abadiy `waiting_production`.

**Haqiqiy hodisa (order 559):** PR#346 MAYDA PISTA +9 ishlab chiqardi, lekin 559 dispatch bo'lmasdan oldin AGT-001 (−5) va AGT-003 (−5) uni iste'mol qildi. `try_confirm_waiting_orders` **all-or-nothing** ishlaydi, lekin stock **birma-bir** bo'shaydi — mana shu nomuvofiqlik ildiz-sabab.

## 2. Maqsad

Buyurtma `waiting_production` ga tushishi bilan **butun savatini band qilsin**; band qilingan miqdorga boshqa hech qanday iste'mol (POS, boshqa agent, xodim mahsulot) tegmasin. Band **FIFO seniority** bilan — eng eski kutayotgan buyurtma birinchi navbatda oladi.

**Qabul qilingan qarorlar (foydalanuvchi 2026-06-06):**
- Ustuvorlik: **kutgan agent buyurtmasi** band qiladi (POS ham band qismga tegolmaydi).
- Band doirasi: **butun savat** (allaqachon omborda bor item'lar ham, ishlab chiqarilayotganlari ham).
- Yondashuv: **A — hisoblanadigan band** (saqlanmaydi, drift-immune).

## 3. Yondashuv A — Hisoblanadigan band (status'dan kelib chiqadi)

Band **hech qayerda saqlanmaydi**. Har safar `waiting_production` statusdagi buyurtmalardan hisoblanadi. Buyurtma statusi o'zgarsa (dispatch/cancel/revert), band avtomatik yo'qoladi → **sinxronlash muammosi yo'q, drift mumkin emas**. Bu loyiha'ning "ledger = haqiqat" falsafasiga mos ([[feedback-stock-at-date-quantity-after-rule]] bilan bir oilada).

### 3.1. Yangi modul: `app/services/stock_reservation.py`

```python
from sqlalchemy import func, or_, and_
from app.models.database import Order, OrderItem, Stock


def get_reserved_quantity(db, warehouse_id, product_id, before_order=None) -> float:
    """waiting_production buyurtmalar band qilgan miqdor (wh+pid bo'yicha).

    before_order berilsa — faqat o'sha buyurtmadan ESKI waiting buyurtmalar
    hisoblanadi (FIFO seniority). O'zini hisobga olmaydi.
    """
    q = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0.0))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.status == "waiting_production",
            Order.type == "sale",
            OrderItem.product_id == product_id,
            func.coalesce(OrderItem.warehouse_id, Order.warehouse_id) == warehouse_id,
        )
    )
    if before_order is not None:
        q = q.filter(
            Order.id != before_order.id,
            or_(
                Order.date < before_order.date,
                and_(Order.date == before_order.date, Order.id < before_order.id),
            ),
        )
    return float(q.scalar() or 0.0)


def get_available_stock(db, warehouse_id, product_id, before_order=None) -> float:
    """Iste'mol uchun mavjud = jismoniy qoldiq − band (seniority bo'yicha)."""
    st = (
        db.query(func.coalesce(func.sum(Stock.quantity), 0.0))
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == product_id)
        .scalar()
    )
    physical = float(st or 0.0)
    reserved = get_reserved_quantity(db, warehouse_id, product_id, before_order)
    return physical - reserved
```

### 3.2. Mantiq

- **Yangi iste'molchi** (POS sotuv, xodim mahsulot, transfer) → `before_order=None` → BARCHA waiting band ayriladi.
- **Buyurtma X ni dispatch** (X o'zi waiting_production yoki dispatch bo'layapti) → `before_order=X` → faqat X'dan **eski** waiting buyurtmalar band ayriladi (X o'z bandini iste'mol qiladi).
- Seniority kafolati: eng eski waiting buyurtma birinchi stock oladi; yangilari va POS kutadi → **starvation yo'q**.

## 4. Call-site o'zgarishlari

Barcha iste'mol darvozalari `get_available_stock()` ishlatadi.

### Faza 1 — sotuv/dispatch darvozalari (asl bug shu yerda)

| Fayl:qator | Funksiya | `before_order` |
|------------|----------|----------------|
| `sales.py:948` | `sales_confirm` (POS) — `have = stock.quantity` | `None` (yangi iste'mol) |
| `sales.py:1128` | `sales_dispatch` (agent) — `available = stock.quantity` | `order` (dispatch bo'layotgan X) |
| `agent_order_service.py:64` | `try_confirm_waiting_orders` — `have = stock.quantity` | `order` (navbatdagi X) |
| `sales.py:2791` | POS xodim mahsulot — `avail` | `None` |
| `employees_product_purchases.py:281` | xodim mahsulot xaridi — `available` | `None` |

### Faza 2 — izchillik uchun (manager amallari, keyinroq)

| Fayl:qator | Funksiya | Qaror |
|------------|----------|-------|
| `warehouse.py:656, 828` | ombor transfer (chiqish) | band ayrilsin yoki "band X dona" ogohlantirish + admin override |
| `production_convert.py:214` | konversiya (manba sarf) | bir xil |

## 5. Edge case va to'g'rilik

- **FIFO seniority:** `before_order` filtri eng eski buyurtmaga ustunlik beradi. Yangi va POS kutadi.
- **`try_confirm_waiting_orders` har buyurtmadan keyin commit qiladi** (mavjud) → keyingi buyurtma yangilangan qoldiqni ko'radi.
- **Driver tanlanmagan** waiting buyurtma baribir band qiladi (savatini ushlaydi) — to'g'ri, supervisor driver tanlagach chiqishi kerak.
- **Birinchi dispatch** (draft→confirmed→dispatch): buyurtma hali waiting_production emas → o'zini band qilmaydi; `before_order=X` faqat eski waiting'larni filtrlaydi, muammo yo'q.
- **Epsilon:** mavjud `+ 1e-6` taqqoslash saqlanadi (`available + 1e-6 < need`).
- **Manfiy available:** over-reservation bo'lsa `available < 0` → `available >= need` rad etadi (to'g'ri, iste'mol bloklanadi).
- **POS bloklanishi:** qabul qilingan — agentga va'da qilingan mahsulotni POS ololmaydi. Admin override Faza 2.
- **Performance:** har (wh,pid) tekshiruvida bitta agregat so'rov. Waiting buyurtmalar kam → arzon. Kelajakda batch qilish mumkin.

## 6. Test strategiyasi

- **Unit (`get_reserved_quantity`):** `before_order` bilan/siz; ko'p waiting buyurtma; FIFO tartibi (eski/yangi date+id); o'zini hisobga olmaslik.
- **Integration:** 2 waiting buyurtma 1 mahsulotga, stock faqat bittasiga yetadi → eski dispatch, yangi kutadi.
- **Regression (559 ssenariysi):** waiting buyurtma savati band, boshqa POS/agent sotuv band item'ni ololmaydi.
- **Konsistentlik:** waiting buyurtma yo'q bo'lganda `get_available_stock` = `Stock.quantity` (band 0).

## 7. Doiradan tashqari (kelajak)

- Admin override (POS shoshilinch sotuvni band ustidan o'tkazishi).
- Faza 2 transfer/conversion hard-block.
- Qisman dispatch (ba'zi item tayyor bo'lsa shularni jo'natish).
- Reservation'ni UI'da ko'rsatish ("Jismoniy: 13 | Band: 10 | Erkin: 3").

## 8. Riskni baholash

- **Ma'lumotga ta'sir:** Yo'q (band saqlanmaydi, faqat o'qish-vaqti hisoblash).
- **Xulq o'zgarishi:** POS/agent sotuv band item'larda bloklanishi mumkin — bu **maqsadli**. Operatorlar "band" sababini ko'rishi uchun Faza 2 UI foydali.
- **Deploy:** Faza 1 read-only logika o'zgarishi; restart kerak. Tier B (xulq o'zgaradi) — tungi oyna + smoke.
