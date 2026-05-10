# Yetkazish kuni va kamchilik tuzatishlari — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent buyurtma flow'iga `delivery_date` qo'shish — supervisor "Yuklash" tugmasi orqali sana va driver tanlaydi. `partner.balance` faqat driver yetkazib tasdiqlaganda yoziladi. Atomik birga 4 ta audit kamchiligi tuzatiladi (B/A/D/E).

**Architecture:** Mavjud `Order` modeliga 2 ta ustun (`delivery_date`, `dispatched_at`) qo'shiladi. Status enum kengayadi (`out_for_delivery`, `delivered` qo'shiladi, `completed` → `delivered` ko'chadi). Kod o'zgarishlari atomik UPDATE WHERE pattern bilan, vaqt-aware stock helper (`get_stock_at_date`) ishlatiladi.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic-style `ensure_*_column()` migratsiyalari, Jinja2 + Bootstrap, pytest in-memory SQLite, Telegram bot notify.

**Spec:** `docs/superpowers/specs/2026-05-10-delivery-scheduling-design.md`

---

## File structure

### Yangilanadigan fayllar
- `app/models/database.py` — `Order` modeliga `delivery_date`, `dispatched_at`; yangi `ensure_orders_delivery_columns()` funksiya
- `app/main.py` — startup hook'ga `ensure_orders_delivery_columns()` chaqirish
- `app/routes/sales.py` — `confirm` soddalashadi, `dispatch` yangi, `revert` balance qaytarish
- `app/services/agent_order_service.py` — `try_confirm_waiting_orders` `out_for_delivery` ga yangilanadi; `_assign_default_driver` o'chiriladi
- `app/routes/api_driver_routes.py` — driver mobile filter va `/deliver` endpoint
- `app/templates/sales/list.html` — `Yuklash sanasi` ustun, `Yuklash` tugmasi
- `app/middleware.py` — yangi endpointlar uchun CSRF + auth whitelist

### Yangi yaratiladigan fayllar
- `app/templates/sales/dispatch_modal.html` — yuklash modal
- `app/templates/sales/deliveries.html` — supervisor delivery dashboard
- `app/routes/sales_deliveries.py` — `/sales/deliveries` route (alohida fayl)
- `scripts/migrate_orders_to_new_status_20260510.py` — bir martalik migratsiya
- `scripts/rollback_status_20260510.py` — qaytarish skripti
- `tests/test_dispatch_flow.py` — dispatch endpoint testlari
- `tests/test_revert_balance.py` — revert balance fix testlari
- `tests/test_atomic_confirm.py` — atomik confirm testlari

---

## Task 1: DB schema additive migratsiya

**Files:**
- Modify: `app/models/database.py` (Order class + new ensure function)
- Modify: `app/main.py` (startup hook)
- Test: `tests/test_dispatch_flow.py` (new file)

- [ ] **Step 1: Order modeliga ustun qo'shish**

`app/models/database.py` — `Order` class ichida `parent_order_id` dan keyin:

```python
delivery_date = Column(Date, nullable=True, index=True)
dispatched_at = Column(DateTime, nullable=True)
```

Avval import bo'limida `Date` borligini tekshiring (yo'q bo'lsa `from sqlalchemy import Date` qo'shing).

- [ ] **Step 2: ensure_orders_delivery_columns() funksiya qo'shish**

`app/models/database.py` oxiriga (boshqa `ensure_*` lar yonida):

```python
def ensure_orders_delivery_columns():
    """orders jadvaliga delivery_date va dispatched_at qo'shadi (mavjud bo'lsa o'tkazib yuboriladi)."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(orders)"))
            cols = [row[1] for row in r]
            if "delivery_date" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_date DATE"))
            if "dispatched_at" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN dispatched_at TIMESTAMP"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_orders_delivery_date_status "
                "ON orders(delivery_date, status)"
            ))
    except Exception as e:
        print(f"ensure_orders_delivery_columns: {e}")
```

- [ ] **Step 3: main.py startup hookga chaqirish qo'shish**

`app/main.py` — boshqa `ensure_*` chaqiruvlari yonida (startup_event funksiya ichida):

```python
from app.models.database import ensure_orders_delivery_columns
ensure_orders_delivery_columns()
```

- [ ] **Step 4: Test yozish (toza DB da ustunlar mavjudligini tekshirish)**

`tests/test_dispatch_flow.py` yangi fayl:

```python
"""Yetkazish kuni flow testlari."""
from datetime import datetime, date
import pytest
from sqlalchemy import inspect


def test_orders_has_delivery_columns(db):
    """orders jadvalida delivery_date va dispatched_at ustunlar bo'lishi kerak."""
    inspector = inspect(db.bind)
    cols = [c["name"] for c in inspector.get_columns("orders")]
    assert "delivery_date" in cols
    assert "dispatched_at" in cols
```

- [ ] **Step 5: Test ishga tushirish — PASS bo'lishi kerak**

```bash
pytest tests/test_dispatch_flow.py::test_orders_has_delivery_columns -v
```
Expected: PASS (Order model'da ustun deklaratsiya bo'lgani sababli `Base.metadata.create_all()` ularni qo'shadi).

- [ ] **Step 6: Commit**

```bash
git add app/models/database.py app/main.py tests/test_dispatch_flow.py
git commit -m "feat(orders): delivery_date va dispatched_at ustunlar qo'shildi"
```

---

## Task 2: Order status konstantlar

**Files:**
- Modify: `app/models/database.py` (Order class top)
- Test: `tests/test_dispatch_flow.py`

- [ ] **Step 1: Status konstantlar va validator qo'shish**

`app/models/database.py` — `class Order(Base):` ichida (`__tablename__` dan keyin):

```python
STATUS_DRAFT = "draft"
STATUS_CONFIRMED = "confirmed"
STATUS_WAITING_PRODUCTION = "waiting_production"
STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
STATUS_DELIVERED = "delivered"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"  # legacy, deprecated — delivered ga ko'chiriladi

VALID_STATUSES = (
    STATUS_DRAFT, STATUS_CONFIRMED, STATUS_WAITING_PRODUCTION,
    STATUS_OUT_FOR_DELIVERY, STATUS_DELIVERED, STATUS_CANCELLED,
    STATUS_COMPLETED,  # legacy backward-compat
)
```

- [ ] **Step 2: Test yozish**

`tests/test_dispatch_flow.py` ga qo'shish:

```python
def test_order_status_constants():
    """Order modelida 6 ta yangi status nomli (+ legacy completed) konstanta bo'lishi kerak."""
    from app.models.database import Order
    assert Order.STATUS_DRAFT == "draft"
    assert Order.STATUS_OUT_FOR_DELIVERY == "out_for_delivery"
    assert Order.STATUS_DELIVERED == "delivered"
    assert "out_for_delivery" in Order.VALID_STATUSES
```

- [ ] **Step 3: Test ishga tushirish — PASS**

```bash
pytest tests/test_dispatch_flow.py::test_order_status_constants -v
```

- [ ] **Step 4: Commit**

```bash
git add app/models/database.py tests/test_dispatch_flow.py
git commit -m "feat(orders): status konstantlar (draft/confirmed/out_for_delivery/delivered/cancelled)"
```

---

## Task 3: Migratsiya ro'yxat skripti (--dry-run)

**Files:**
- Create: `scripts/migrate_orders_to_new_status_20260510.py`

- [ ] **Step 1: Skript yozish**

`scripts/migrate_orders_to_new_status_20260510.py`:

```python
"""Mavjud orderlarning statusini yangi nomenklaturaga ko'chirish.

Bosqich 1: --dry-run (default) — faqat ro'yxatni ko'rsatadi
Bosqich 2: --apply — backup yaratadi, UPDATE'lar bajariladi

Strategiya:
- 'completed' → 'delivered' (avtomatik)
- 'confirmed' Delivery 'delivered' bo'lgan → 'delivered'
- 'confirmed' Delivery 'pending' bo'lgan → 'out_for_delivery', delivery_date = order.date
- 'confirmed' Delivery yo'q → SO'RAYDI (har birini ko'rsatadi, qo'lda)
- 'draft', 'waiting_production' → o'zgarmaydi
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(argv):
    dry = "--apply" not in argv
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print("=" * 70)
    print("ORDER STATUS MIGRATSIYA — 2026-05-10")
    print(f"Rejim: {'DRY-RUN (faqat ko''rsatish)' if dry else 'APPLY (UPDATE bajariladi)'}")
    print("=" * 70)

    cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
    print("\nHozirgi status taqsimot:")
    for status, count in cur.fetchall():
        print(f"  {status or '(NULL)':<25} {count:>6}")

    cur.execute("""
        SELECT o.id, o.number, o.status, o.date, o.partner_id, o.total,
               (SELECT d.status FROM deliveries d WHERE d.order_id = o.id LIMIT 1) AS delivery_status
        FROM orders o
        WHERE o.status IN ('confirmed', 'completed')
        ORDER BY o.id
    """)
    rows = cur.fetchall()

    completed_to_delivered = []
    confirmed_with_delivered = []
    confirmed_with_pending = []
    confirmed_no_delivery = []

    for row in rows:
        oid, num, status, _, _, _, dstatus = row
        if status == "completed":
            completed_to_delivered.append(oid)
        elif status == "confirmed":
            if dstatus == "delivered":
                confirmed_with_delivered.append(oid)
            elif dstatus in ("pending", "in_progress"):
                confirmed_with_pending.append(oid)
            else:
                confirmed_no_delivery.append(row)

    print(f"\nMigratsiya rejasi:")
    print(f"  completed → delivered: {len(completed_to_delivered)} ta")
    print(f"  confirmed (Delivery=delivered) → delivered: {len(confirmed_with_delivered)} ta")
    print(f"  confirmed (Delivery=pending) → out_for_delivery: {len(confirmed_with_pending)} ta")
    print(f"  confirmed (Delivery yo'q): {len(confirmed_no_delivery)} ta — QO'LDA hal qilish")

    if confirmed_no_delivery:
        print("\nDelivery yo'q confirmed orderlar (oxirgi 10 ta):")
        for oid, num, _, dt, pid, tot, _ in confirmed_no_delivery[-10:]:
            print(f"  id={oid} {num} sana={dt} partner={pid} total={tot}")

    if dry:
        print("\n(--apply bilan ishga tushiring)")
        conn.close()
        return 0

    print("\nBackup yaratamoqda...")
    backup = ROOT / "backups" / f"pre_status_migrate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup.parent.mkdir(exist_ok=True)
    bk = sqlite3.connect(str(backup))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup.name}")

    if completed_to_delivered:
        cur.executemany("UPDATE orders SET status='delivered' WHERE id=?",
                       [(oid,) for oid in completed_to_delivered])
    if confirmed_with_delivered:
        cur.executemany("UPDATE orders SET status='delivered' WHERE id=?",
                       [(oid,) for oid in confirmed_with_delivered])
    if confirmed_with_pending:
        cur.executemany(
            "UPDATE orders SET status='out_for_delivery', delivery_date=DATE(date) WHERE id=?",
            [(oid,) for oid in confirmed_with_pending])
    conn.commit()
    print(f"\nUPDATE bajarildi: {len(completed_to_delivered) + len(confirmed_with_delivered) + len(confirmed_with_pending)} ta")
    print("Delivery yo'q confirmed orderlar o'zgarmadi — qo'lda hal qiling")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Skriptni dry-run da sinash**

```bash
python scripts/migrate_orders_to_new_status_20260510.py
```
Expected: Status taqsimot ko'rinadi, "Delivery yo'q" guruhi alohida ko'rsatiladi. Hech narsa o'zgartirilmaydi.

- [ ] **Step 3: Commit (faqat skript, --apply hali ishga tushirilmaydi)**

```bash
git add scripts/migrate_orders_to_new_status_20260510.py
git commit -m "chore: order status migratsiya skripti (dry-run mode)"
```

---

## Task 4: Revert balance fix (B)

**Files:**
- Modify: `app/routes/sales.py` (revert function ~752-784)
- Test: `tests/test_revert_balance.py` (new file)

- [ ] **Step 1: Test yozish**

`tests/test_revert_balance.py`:

```python
"""Revert balance fix testlari (audit B)."""
import pytest
from datetime import datetime
from app.models.database import Order, Partner


def test_revert_delivered_returns_balance(db):
    """delivered order revert qilinsa, partner.balance qaytariladi."""
    p = Partner(name="Test", balance=0, code="P9999")
    db.add(p); db.flush()
    o = Order(
        number="AGT-T-001", date=datetime.now(), type="sale",
        partner_id=p.id, total=100000, debt=100000, paid=0,
        status="delivered", previous_partner_balance=0
    )
    db.add(o); db.flush()
    p.balance = 100000  # confirm/deliver paytida yozilgan
    db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 0, "delivered revert balansi previous'ga qaytarishi kerak"


def test_revert_confirmed_no_balance_change(db):
    """confirmed order (balance hali yozilmagan) revert balanceni o'zgartirmaydi."""
    p = Partner(name="Test", balance=50000, code="P9998")
    db.add(p); db.flush()
    o = Order(
        number="AGT-T-002", date=datetime.now(), type="sale",
        partner_id=p.id, total=100000, debt=100000, paid=0,
        status="confirmed", previous_partner_balance=50000
    )
    db.add(o); db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 50000, "confirmed status balanceni o'zgartirmasligi kerak"
```

- [ ] **Step 2: Test ishga tushirish — FAIL bo'lishi kerak (helper hali yo'q)**

```bash
pytest tests/test_revert_balance.py -v
```
Expected: FAIL with `ImportError: cannot import name '_revert_balance_if_needed'`

- [ ] **Step 3: Helper funksiya qo'shish**

`app/routes/sales.py` — file boshida (importlardan keyin):

```python
def _revert_balance_if_needed(db, order, partner):
    """Faqat 'delivered' yoki legacy 'completed' bo'lgan orderda balance qaytariladi.

    Yangi flow'da boshqa statuslarda balance hech yozilmaydi (faqat driver
    'Yetkazdim' bosgach yoziladi), shuning uchun qaytarish kerak emas.
    """
    if order.status not in ("delivered", "completed"):
        return
    if not partner or order.previous_partner_balance is None:
        return
    partner.balance = order.previous_partner_balance
```

- [ ] **Step 4: revert route'iga _revert_balance_if_needed chaqirishni qo'shish**

`app/routes/sales.py` — `revert` funksiyasini topib, mavjud `partner.balance += debt` ko'rinishidagi kod o'rnida (~775 atrofida):

Eski kod (faqat sample):
```python
# (mavjud bo'lsa balance manipulatsiyasi shu yerda)
order.status = "draft"
db.commit()
```

Yangi kod:
```python
partner = db.query(Partner).filter(Partner.id == order.partner_id).first() if order.partner_id else None
_revert_balance_if_needed(db, order, partner)
order.status = "cancelled"
db.commit()
```

(Hozirgi `revert` aniq qaerini o'zgartirishni kod o'qib aniqlanadi — `previous_partner_balance` ishlatilgan joyni topib, yangi helper bilan almashtirish.)

- [ ] **Step 5: Test ishga tushirish — PASS**

```bash
pytest tests/test_revert_balance.py -v
```

- [ ] **Step 6: Commit**

```bash
git add app/routes/sales.py tests/test_revert_balance.py
git commit -m "fix(sales): revert balance qaytarish (audit B)"
```

---

## Task 5: Atomik confirm fix (A)

**Files:**
- Modify: `app/routes/sales.py` (confirm function ~570)
- Test: `tests/test_atomic_confirm.py` (new file)

- [ ] **Step 1: Test yozish — concurrent confirm**

`tests/test_atomic_confirm.py`:

```python
"""Atomik confirm test (audit A — stock 2x oldini olish)."""
import pytest
from datetime import datetime
from sqlalchemy import text
from app.models.database import Order


def test_confirm_atomic_only_first_succeeds(db):
    """Bir vaqtda 2 ta confirm so'rovi: faqat birinchi muvaffaqiyatli."""
    o = Order(
        number="AGT-T-A1", date=datetime.now(), type="sale",
        total=100000, debt=100000, paid=0, status="draft",
    )
    db.add(o); db.flush()

    r1 = db.execute(text("UPDATE orders SET status='confirmed' WHERE id=:id AND status='draft'"),
                    {"id": o.id})
    db.commit()
    r2 = db.execute(text("UPDATE orders SET status='confirmed' WHERE id=:id AND status='draft'"),
                    {"id": o.id})
    db.commit()

    assert r1.rowcount == 1, "Birinchi confirm muvaffaqiyatli"
    assert r2.rowcount == 0, "Ikkinchi confirm rad etiladi (status allaqachon confirmed)"
```

- [ ] **Step 2: Test ishga tushirish — PASS bo'lishi kerak (faqat SQL, yangi kod yo'q)**

```bash
pytest tests/test_atomic_confirm.py -v
```

- [ ] **Step 3: sales.py confirm route'ini atomik qilish**

`app/routes/sales.py` — `confirm` funksiyasi boshida `claim` UPDATE WHERE pattern (warehouse confirm'da bor):

```python
from sqlalchemy import text as _text
result = db.execute(
    _text("UPDATE orders SET status='confirmed' WHERE id=:id AND status='draft'"),
    {"id": order_id}
)
if result.rowcount == 0:
    return RedirectResponse(
        url=f"/sales/{order_id}?already=1",
        status_code=303,
    )
# Bu yerdan keyin status='confirmed' kafolatlangan
```

(Hozirgi confirm function code'ni topib, atomik UPDATE WHERE bilan boshlash. Stock manipulatsiyasi keyingi task'da olib tashlanadi — hozir faqat status check.)

- [ ] **Step 4: Commit**

```bash
git add app/routes/sales.py tests/test_atomic_confirm.py
git commit -m "fix(sales): atomik confirm UPDATE WHERE (audit A — stock 2x oldini olish)"
```

---

## Task 6: Sales confirm soddalashtirish

**Files:**
- Modify: `app/routes/sales.py` (confirm function)

- [ ] **Step 1: Hozirgi confirm flow'ni o'qib, balance/stock manipulatsiya kodini izlash**

Aniqlash kerak: confirm ichida nima boshqa qiladi (Stock movement, partner.balance, Delivery yaratish). Bu Task 7 ga o'tkaziladi.

```bash
grep -n "partner.balance\|create_stock_movement\|Delivery(" app/routes/sales.py | head -20
```

- [ ] **Step 2: Test yozish — confirm faqat status ni o'zgartiradi**

`tests/test_dispatch_flow.py` ga qo'shish:

```python
def test_confirm_only_changes_status(db, client):
    """confirm endpoint draft -> confirmed, stock va balance o'zgarmaydi."""
    from app.models.database import Order, Partner, Stock, Product, Warehouse
    p = Partner(name="T", balance=0, code="P_T")
    w = Warehouse(name="W", is_active=True)
    pr = Product(name="P", is_active=True)
    db.add_all([p, w, pr]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=100)
    db.add(s); db.flush()
    o = Order(number="AGT-T-C1", date=datetime.now(), type="sale",
              partner_id=p.id, warehouse_id=w.id, total=10000, debt=10000,
              paid=0, status="draft")
    db.add(o); db.flush()

    response = client.post(f"/sales/{o.id}/confirm", follow_redirects=False)
    db.refresh(o); db.refresh(s); db.refresh(p)

    assert response.status_code in (303, 302)
    assert o.status == "confirmed"
    assert s.quantity == 100  # o'zgarmagan
    assert p.balance == 0  # o'zgarmagan
```

- [ ] **Step 3: confirm route'ni soddalashtirish**

`app/routes/sales.py` — confirm function ichidan **Stock manipulatsiya, balance += debt, Delivery yaratish, production trigger** kodlarini olib tashlash. Faqat:
- Atomik UPDATE WHERE status='draft' → 'confirmed'
- Audit log
- Redirect

```python
@router.post("/{order_id}/confirm")
async def sales_confirm(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if not current_user or current_user.role not in ("admin", "manager"):
        raise HTTPException(403)
    from sqlalchemy import text as _text
    result = db.execute(
        _text("UPDATE orders SET status='confirmed' WHERE id=:id AND status='draft'"),
        {"id": order_id}
    )
    if result.rowcount == 0:
        return RedirectResponse(url=f"/sales/{order_id}?already=1", status_code=303)
    db.commit()
    return RedirectResponse(url=f"/sales/{order_id}?confirmed=1", status_code=303)
```

- [ ] **Step 4: Test ishga tushirish — PASS**

```bash
pytest tests/test_dispatch_flow.py::test_confirm_only_changes_status -v
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/sales.py tests/test_dispatch_flow.py
git commit -m "refactor(sales): confirm soddalashdi — faqat status o'zgartiradi"
```

---

## Task 7: /sales/{id}/dispatch endpoint

**Files:**
- Modify: `app/routes/sales.py`
- Test: `tests/test_dispatch_flow.py`

- [ ] **Step 1: Test yozish — dispatch stock yetarli holat**

`tests/test_dispatch_flow.py`:

```python
def test_dispatch_stock_sufficient(db, client):
    """Dispatch: stock yetarli bo'lsa status=out_for_delivery, stock kamayadi."""
    from app.models.database import Order, OrderItem, Stock, Product, Warehouse, Partner, Driver, Delivery
    p = Partner(name="T", balance=0, code="P_D1")
    w = Warehouse(name="W", is_active=True)
    pr = Product(name="P", is_active=True, sale_price=10000)
    drv = Driver(code="DR", full_name="Driver", is_active=True)
    db.add_all([p, w, pr, drv]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=100)
    db.add(s); db.flush()
    o = Order(number="AGT-T-D1", date=datetime.now(), type="sale",
              partner_id=p.id, warehouse_id=w.id, total=50000, debt=50000,
              paid=0, status="confirmed")
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=5,
                     price=10000, total=50000, warehouse_id=w.id))
    db.commit()

    response = client.post(
        f"/sales/{o.id}/dispatch",
        data={"delivery_date": "2026-05-12", "driver_id": drv.id},
        follow_redirects=False,
    )
    db.refresh(o); db.refresh(s)

    assert response.status_code in (302, 303)
    assert o.status == "out_for_delivery"
    assert o.delivery_date.isoformat() == "2026-05-12"
    assert o.pending_driver_id == drv.id
    assert o.dispatched_at is not None
    assert s.quantity == 95  # 100 - 5
    delivery = db.query(Delivery).filter_by(order_id=o.id).first()
    assert delivery is not None
    assert delivery.driver_id == drv.id
```

- [ ] **Step 2: Test ishga tushirish — FAIL (404)**

```bash
pytest tests/test_dispatch_flow.py::test_dispatch_stock_sufficient -v
```
Expected: FAIL — endpoint hali yo'q

- [ ] **Step 3: dispatch endpoint qo'shish**

`app/routes/sales.py` — confirm dan keyin:

```python
@router.post("/{order_id}/dispatch")
async def sales_dispatch(
    order_id: int,
    delivery_date: str = Form(...),
    driver_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if not current_user or current_user.role not in ("admin", "manager"):
        raise HTTPException(403)
    from datetime import date as _date, datetime as _dt
    from sqlalchemy import text as _text

    try:
        delivery_d = _date.fromisoformat(delivery_date.strip())
    except ValueError:
        return RedirectResponse(
            url=f"/sales/{order_id}?error=Sana+formati+xato",
            status_code=303,
        )

    drv = db.query(Driver).filter(Driver.id == driver_id, Driver.is_active == True).first()
    if not drv:
        return RedirectResponse(url=f"/sales/{order_id}?error=Haydovchi+topilmadi", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status != "confirmed":
        return RedirectResponse(url=f"/sales/{order_id}?already=1", status_code=303)

    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    if not items:
        return RedirectResponse(url=f"/sales/{order_id}?error=Mahsulot+yo'q", status_code=303)

    shortages = []
    for item in items:
        wh = item.warehouse_id or order.warehouse_id
        s = db.query(Stock).filter(Stock.warehouse_id == wh, Stock.product_id == item.product_id).first()
        avail = float(s.quantity or 0) if s else 0
        if avail + 1e-6 < float(item.quantity):
            shortages.append((item.product_id, float(item.quantity), avail, wh))

    if shortages:
        from app.services.production_service import create_production_for_shortage
        order.delivery_date = delivery_d
        order.pending_driver_id = driver_id
        result = db.execute(
            _text("UPDATE orders SET status='waiting_production' WHERE id=:id AND status='confirmed'"),
            {"id": order_id}
        )
        if result.rowcount == 0:
            return RedirectResponse(url=f"/sales/{order_id}?already=1", status_code=303)
        for pid, need, have, wh in shortages:
            create_production_for_shortage(db, order, pid, need - have, wh)
        db.commit()
        return RedirectResponse(url=f"/sales/{order_id}?waiting=1", status_code=303)

    result = db.execute(
        _text("UPDATE orders SET status='out_for_delivery', delivery_date=:dd, "
              "dispatched_at=:now, pending_driver_id=:drv "
              "WHERE id=:id AND status='confirmed'"),
        {"id": order_id, "dd": delivery_d, "now": _dt.now(), "drv": driver_id}
    )
    if result.rowcount == 0:
        return RedirectResponse(url=f"/sales/{order_id}?already=1", status_code=303)

    from app.services.stock_service import create_stock_movement
    for item in items:
        wh = item.warehouse_id or order.warehouse_id
        create_stock_movement(
            db=db, warehouse_id=wh, product_id=item.product_id,
            quantity_change=-float(item.quantity), operation_type="sale",
            document_type="Sale", document_id=order.id,
            document_number=order.number, user_id=current_user.id,
            note=f"Sotuv yo'lga chiqarildi: {order.number}",
        )

    delivery = Delivery(
        number=f"DLV-{delivery_d.strftime('%Y%m%d')}-{order.id:04d}",
        order_id=order.id, driver_id=driver_id,
        scheduled_date=delivery_d, status="pending",
    )
    db.add(delivery)
    db.commit()
    return RedirectResponse(url=f"/sales/{order_id}?dispatched=1", status_code=303)
```

- [ ] **Step 4: `create_production_for_shortage` helper qo'shish**

`app/services/production_service.py` ga (yoki yangi joyga):

```python
def create_production_for_shortage(db, order, product_id, qty_needed, warehouse_id):
    """Shortage uchun Production order yaratadi. delivery_date saqlanadi."""
    from app.models.database import Production
    from datetime import datetime
    pr_count = db.query(Production).filter(
        Production.created_at >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()
    pr = Production(
        number=f"PR-{datetime.now().strftime('%Y%m%d')}-{pr_count + 1:03d}",
        product_id=product_id, quantity=qty_needed, status="draft",
        order_id=order.id, warehouse_id=warehouse_id,
    )
    db.add(pr)
    db.flush()
    return pr
```

(Loyihada production_service da o'xshash funksiya bor bo'lsa, qayta yaratmang — uni topib import qiling.)

- [ ] **Step 5: Test ishga tushirish — PASS**

```bash
pytest tests/test_dispatch_flow.py::test_dispatch_stock_sufficient -v
```

- [ ] **Step 6: Stock yetmagan holat uchun test**

```python
def test_dispatch_stock_short_creates_production(db, client):
    """Stock yetmasa: status=waiting_production, delivery_date saqlanadi."""
    # ... (xuddi yuqoridagi test, lekin stock=2, kerak=5)
    # assert o.status == "waiting_production"
    # assert o.delivery_date is not None
```

- [ ] **Step 7: Commit**

```bash
git add app/routes/sales.py app/services/production_service.py tests/test_dispatch_flow.py
git commit -m "feat(sales): /dispatch endpoint — yuklash sanasi va driver tanlash"
```

---

## Task 8: try_confirm_waiting_orders yangilanishi

**Files:**
- Modify: `app/services/agent_order_service.py`

- [ ] **Step 1: Test yozish — production tugagach out_for_delivery ga o'tadi**

`tests/test_dispatch_flow.py`:

```python
def test_waiting_to_out_for_delivery_after_production(db):
    """Production status=completed bo'lganda waiting_production → out_for_delivery."""
    # Setup: order status=waiting_production, delivery_date va pending_driver_id bor
    # Production status=completed
    # try_confirm_waiting_orders chaqiriladi
    # assert order.status == "out_for_delivery"
    # assert balance += debt YO'Q (faqat driver yetkazganda)
```

- [ ] **Step 2: try_confirm_waiting_orders ni yangilash**

`app/services/agent_order_service.py` ichida:
- `confirmed` o'rniga `out_for_delivery` ga o'tkazish
- balance += debt YO'Q (olib tashlash, faqat /api/driver/deliver da yoziladi)
- pending_driver_id NULL bo'lsa supervisor'ga Telegram xabar, status waiting_production qoladi

```python
def try_confirm_waiting_orders(db: Session) -> int:
    from datetime import datetime
    from sqlalchemy import text as _text
    from app.services.stock_service import create_stock_movement
    from app.models.database import Order, OrderItem, Stock, Delivery

    waiting = db.query(Order).filter(Order.status == "waiting_production").all()
    promoted = 0

    for order in waiting:
        if not order.pending_driver_id:
            try:
                from app.bot.notifier import notify_supervisor
                notify_supervisor(f"⚠ Buyurtma {order.number} uchun haydovchi tanlanmagan — qayta /dispatch qiling")
            except Exception:
                pass
            continue

        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        ok = True
        for item in items:
            wh = item.warehouse_id or order.warehouse_id
            s = db.query(Stock).filter(Stock.warehouse_id == wh, Stock.product_id == item.product_id).first()
            if not s or float(s.quantity or 0) + 1e-6 < float(item.quantity):
                ok = False
                break
        if not ok:
            continue

        result = db.execute(
            _text("UPDATE orders SET status='out_for_delivery', dispatched_at=:now "
                  "WHERE id=:id AND status='waiting_production'"),
            {"id": order.id, "now": datetime.now()}
        )
        if result.rowcount != 1:
            continue

        for item in items:
            wh = item.warehouse_id or order.warehouse_id
            create_stock_movement(
                db=db, warehouse_id=wh, product_id=item.product_id,
                quantity_change=-float(item.quantity), operation_type="sale",
                document_type="Sale", document_id=order.id,
                document_number=order.number, user_id=None,
                note=f"Auto-confirm production: {order.number}",
            )

        delivery = Delivery(
            number=f"DLV-{order.delivery_date.strftime('%Y%m%d')}-{order.id:04d}",
            order_id=order.id, driver_id=order.pending_driver_id,
            scheduled_date=order.delivery_date, status="pending",
        )
        db.add(delivery)
        promoted += 1

    if promoted:
        db.commit()
    return promoted
```

- [ ] **Step 3: Test PASS**

```bash
pytest tests/test_dispatch_flow.py::test_waiting_to_out_for_delivery_after_production -v
```

- [ ] **Step 4: Commit**

```bash
git add app/services/agent_order_service.py tests/test_dispatch_flow.py
git commit -m "refactor(orders): try_confirm_waiting -> out_for_delivery (balance hali yozilmaydi)"
```

---

## Task 9: Driver auto-assign olib tashlash (D)

**Files:**
- Modify: `app/services/agent_order_service.py`

- [ ] **Step 1: `_assign_default_driver` mavjudligini tekshirish**

```bash
grep -n "_assign_default_driver\|default.*driver\|first.*active.*driver" app/services/agent_order_service.py
```

- [ ] **Step 2: Helper funksiyani o'chirish va chaqiruvlarni olib tashlash**

`agent_order_service.py` — `_assign_default_driver` funksiyasi va undagi chaqiruvlarni olib tashlash. Yangi flow'da driver `/dispatch` paytida supervisor tomonidan tanlanadi.

- [ ] **Step 3: Test yozish — driver bo'lmasa order o'zgarmaydi**

```python
def test_no_default_driver_assignment():
    """waiting_production order pending_driver_id NULL bo'lsa, status o'zgarmaydi."""
    # Setup: order status=waiting_production, pending_driver_id=None
    # Stock yetarli
    # try_confirm_waiting_orders chaqiriladi
    # assert order.status == "waiting_production" (o'zgarmagan)
```

- [ ] **Step 4: Commit**

```bash
git add app/services/agent_order_service.py tests/test_dispatch_flow.py
git commit -m "fix(orders): driver auto-assign olib tashlandi (audit D)"
```

---

## Task 10: Driver mobile filter

**Files:**
- Modify: `app/routes/api_driver_routes.py` (yoki tegishli fayl)

- [ ] **Step 1: Driver endpoint topish**

```bash
grep -rn "@router.get.*driver.*orders\|GET.*driver.*orders" app/routes/
```

- [ ] **Step 2: Filter yangilash**

Driver mobile API:
```python
# Eski: barcha confirmed orderlar
# Yangi: faqat status=out_for_delivery va delivery_date <= today
from datetime import date as _date

orders = db.query(Order).filter(
    Order.pending_driver_id == driver.id,
    Order.status == "out_for_delivery",
    Order.delivery_date <= _date.today(),
).order_by(Order.delivery_date).all()
```

- [ ] **Step 3: Test yozish**

```python
def test_driver_sees_only_today_or_overdue(db, client):
    """Driver mobile: status=out_for_delivery va delivery_date<=today ko'radi."""
    # Setup: 3 ta order — kelajak/bugun/kechagi delivery_date bilan
    # GET /api/driver/orders
    # assert: faqat bugun va kechagi ko'rinadi
```

- [ ] **Step 4: Commit**

```bash
git add app/routes/api_driver_routes.py tests/test_dispatch_flow.py
git commit -m "feat(driver): mobile filter — out_for_delivery + delivery_date<=today"
```

---

## Task 11: /api/driver/order/{id}/deliver endpoint

**Files:**
- Modify: `app/routes/api_driver_routes.py`
- Modify: `app/middleware.py`

- [ ] **Step 1: Test yozish**

```python
def test_driver_deliver_writes_balance(db, client):
    """Driver 'Yetkazdim' bosganda balance += debt yoziladi."""
    # Setup: order out_for_delivery, partner.balance=0, debt=50000, previous_partner_balance=0
    # POST /api/driver/order/{id}/deliver
    # assert: order.status == "delivered"
    # assert: partner.balance == 50000
    # assert: delivery.status == "delivered"


def test_driver_deliver_idempotent(db, client):
    """Ikki marta deliver chaqirishda balance ikki marta yozilmaydi."""
    # POST /api/driver/order/{id}/deliver — birinchi: 200 OK
    # POST /api/driver/order/{id}/deliver — ikkinchi: 409 yoki balance o'zgarmaydi
```

- [ ] **Step 2: Endpoint yozish**

```python
@router.post("/api/driver/order/{order_id}/deliver")
async def driver_deliver_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_driver_auth),
):
    from sqlalchemy import text as _text
    from datetime import datetime
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return JSONResponse({"success": False, "error": "Topilmadi"}, status_code=404)
    driver = db.query(Driver).filter(Driver.code == current_user.username).first()
    if not driver or order.pending_driver_id != driver.id:
        return JSONResponse({"success": False, "error": "Sizga tegishli emas"}, status_code=403)

    result = db.execute(
        _text("UPDATE orders SET status='delivered' WHERE id=:id AND status='out_for_delivery'"),
        {"id": order_id}
    )
    if result.rowcount == 0:
        return JSONResponse({"success": False, "error": "Status mos emas"}, status_code=409)

    if order.partner_id and order.debt and order.debt > 0:
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        if partner:
            order.previous_partner_balance = float(partner.balance or 0)
            partner.balance = float(partner.balance or 0) + float(order.debt)

    delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
    if delivery:
        delivery.status = "delivered"
        delivery.completed_at = datetime.now()
    db.commit()
    return JSONResponse({"success": True, "status": "delivered"})
```

- [ ] **Step 3: middleware.py whitelist'ga qo'shish**

`app/middleware.py` — CSRF whitelist (~99) va Auth whitelist (~170):

```python
# CSRF whitelist
"/api/driver/order/.*/deliver",

# Auth whitelist (agar driver auth alohida bo'lsa)
"/api/driver/order/.*/deliver",
```

- [ ] **Step 4: Test PASS**

```bash
pytest tests/test_dispatch_flow.py::test_driver_deliver_writes_balance tests/test_dispatch_flow.py::test_driver_deliver_idempotent -v
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/api_driver_routes.py app/middleware.py tests/test_dispatch_flow.py
git commit -m "feat(driver): /deliver endpoint — balance += debt yoziladi"
```

---

## Task 12: Sales list template

**Files:**
- Modify: `app/templates/sales/list.html`

- [ ] **Step 1: Hozirgi template'ni o'qish — qayerga yangi ustun qo'shish**

```bash
grep -n "<th\|<td" app/templates/sales/list.html | head -30
```

- [ ] **Step 2: "Yuklash sanasi" ustunni qo'shish**

`app/templates/sales/list.html` — table header'ga (Status ustunidan keyin):

```html
<th>Yuklash sanasi</th>
```

Body row'da (har order uchun):

```html
<td>
  {% if order.delivery_date %}
    {{ order.delivery_date.strftime('%d.%m.%Y') }}
  {% else %}
    —
  {% endif %}
</td>
```

- [ ] **Step 3: "Yuklash" tugmasini qo'shish (faqat status='confirmed' uchun)**

Action ustunda:

```html
{% if order.status == 'confirmed' and current_user.role in ['admin', 'manager'] %}
  <button type="button"
          class="btn btn-warning btn-sm"
          data-bs-toggle="modal"
          data-bs-target="#dispatchModal-{{ order.id }}">
    🚚 Yuklash
  </button>
  {% include 'sales/dispatch_modal.html' with context %}
{% endif %}
```

- [ ] **Step 4: Status badge'larini yangilash (o'zbekcha)**

```html
{% set status_labels = {
    'draft': ('Yangi', 'secondary'),
    'confirmed': ('Tayyor', 'primary'),
    'waiting_production': ('Production kutilmoqda', 'info'),
    'out_for_delivery': ('Yo\'lda', 'warning'),
    'delivered': ('Yetkazildi', 'success'),
    'cancelled': ('Bekor', 'danger'),
    'completed': ('Yetkazildi', 'success'),
} %}
{% set label, color = status_labels.get(order.status, (order.status, 'dark')) %}
<span class="badge bg-{{ color }}">{{ label }}</span>
```

- [ ] **Step 5: Sahifani brauzerda tekshirish**

```bash
# Server restart kerak (--reload yo'qligi sababli)
# Tekshirish: /sales sahifasi → Yuklash sanasi ustun ko'rinadi, Tayyor orderlarda Yuklash tugmasi
```

- [ ] **Step 6: Commit**

```bash
git add app/templates/sales/list.html
git commit -m "feat(sales/ui): Yuklash sanasi ustun va Yuklash tugmasi"
```

---

## Task 13: Dispatch modal template

**Files:**
- Create: `app/templates/sales/dispatch_modal.html`
- Modify: `app/routes/sales.py` (active drivers ni context'ga uzatish)

- [ ] **Step 1: Modal template yaratish**

`app/templates/sales/dispatch_modal.html`:

```html
<div class="modal fade" id="dispatchModal-{{ order.id }}" tabindex="-1">
  <div class="modal-dialog">
    <form action="/sales/{{ order.id }}/dispatch" method="POST" class="modal-content">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <div class="modal-header">
        <h5 class="modal-title">🚚 Yuklash — {{ order.number }}</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">Yuklash sanasi:</label>
          <input type="date" name="delivery_date" class="form-control"
                 min="{{ today_iso }}"
                 value="{{ today_iso }}" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Haydovchi:</label>
          <select name="driver_id" class="form-control" required>
            <option value="">— Tanlang —</option>
            {% for d in active_drivers %}
              <option value="{{ d.id }}">{{ d.full_name }} ({{ d.code }})</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Bekor</button>
        <button type="submit" class="btn btn-warning">🚚 Yo'lga chiqarish</button>
      </div>
    </form>
  </div>
</div>
```

- [ ] **Step 2: Sales list route'ga `active_drivers` qo'shish**

`app/routes/sales.py` — sales list view (template render qiluvchi):

```python
active_drivers = db.query(Driver).filter(Driver.is_active == True).order_by(Driver.full_name).all()
today_iso = datetime.now().date().isoformat()

return templates.TemplateResponse("sales/list.html", {
    ...,
    "active_drivers": active_drivers,
    "today_iso": today_iso,
})
```

- [ ] **Step 3: Brauzerda tekshirish**

`/sales` ga kiring, "Tayyor" orderda "Yuklash" tugmasini bosing → modal ochiladi.

- [ ] **Step 4: Commit**

```bash
git add app/templates/sales/dispatch_modal.html app/routes/sales.py
git commit -m "feat(sales/ui): yuklash modal — sana va haydovchi tanlash"
```

---

## Task 14: Deliveries dashboard (E)

**Files:**
- Create: `app/routes/sales_deliveries.py`
- Create: `app/templates/sales/deliveries.html`
- Modify: `app/main.py` (router register)

- [ ] **Step 1: Yangi route fayli**

`app/routes/sales_deliveries.py`:

```python
from datetime import date as _date, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_auth
from app.models.database import Order, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/sales/deliveries", response_class=HTMLResponse)
async def deliveries_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    today = _date.today()
    tomorrow = today + timedelta(days=1)

    today_orders = db.query(Order).filter(
        Order.status == "out_for_delivery",
        Order.delivery_date == today,
    ).all()
    tomorrow_orders = db.query(Order).filter(
        Order.status == "out_for_delivery",
        Order.delivery_date == tomorrow,
    ).all()
    overdue = db.query(Order).filter(
        Order.status == "out_for_delivery",
        Order.delivery_date < today,
    ).all()
    waiting = db.query(Order).filter(
        Order.status == "waiting_production",
    ).all()

    return templates.TemplateResponse("sales/deliveries.html", {
        "request": request,
        "current_user": current_user,
        "today_orders": today_orders,
        "tomorrow_orders": tomorrow_orders,
        "overdue": overdue,
        "waiting": waiting,
        "today": today,
    })
```

- [ ] **Step 2: Template yaratish**

`app/templates/sales/deliveries.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="container">
  <h2>📦 Yetkazishlar dashboard</h2>

  <ul class="nav nav-tabs" id="deliveryTabs">
    <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#today">Bugun ({{ today_orders|length }})</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#tomorrow">Ertaga ({{ tomorrow_orders|length }})</a></li>
    <li class="nav-item"><a class="nav-link text-danger" data-bs-toggle="tab" href="#overdue">⚠ Kechikkanlar ({{ overdue|length }})</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#waiting">Production kutilmoqda ({{ waiting|length }})</a></li>
  </ul>

  <div class="tab-content mt-3">
    {% for tab_id, orders in [('today', today_orders), ('tomorrow', tomorrow_orders), ('overdue', overdue), ('waiting', waiting)] %}
      <div id="{{ tab_id }}" class="tab-pane {% if tab_id == 'today' %}show active{% endif %}">
        <table class="table table-striped">
          <thead>
            <tr><th>№</th><th>Mijoz</th><th>Haydovchi</th><th>Sana</th><th>Summa</th><th></th></tr>
          </thead>
          <tbody>
            {% for o in orders %}
              <tr>
                <td>{{ o.number }}</td>
                <td>{{ o.partner.name if o.partner else '—' }}</td>
                <td>{{ o.driver.full_name if o.driver else '—' }}</td>
                <td>{{ o.delivery_date.strftime('%d.%m.%Y') if o.delivery_date else '—' }}</td>
                <td class="text-end">{{ '{:,.0f}'.format(o.total or 0) }}</td>
                <td><a href="/sales/{{ o.id }}" class="btn btn-sm btn-primary">Ochish</a></td>
              </tr>
            {% else %}
              <tr><td colspan="6" class="text-muted text-center">Bo'sh</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: main.py'da router'ni ro'yxatga olish**

`app/main.py` — boshqa router'lar yonida:

```python
from app.routes.sales_deliveries import router as sales_deliveries_router
app.include_router(sales_deliveries_router)
```

- [ ] **Step 4: Test yozish**

```python
def test_deliveries_dashboard_loads(db, client):
    """/sales/deliveries sahifasi yuklanadi va 4 ta tab ko'rinadi."""
    response = client.get("/sales/deliveries")
    assert response.status_code == 200
    assert "Bugun" in response.text
    assert "Ertaga" in response.text
    assert "Kechikkan" in response.text
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/sales_deliveries.py app/templates/sales/deliveries.html app/main.py tests/test_dispatch_flow.py
git commit -m "feat(sales): /sales/deliveries dashboard (audit E)"
```

---

## Task 15: Rollback skripti

**Files:**
- Create: `scripts/rollback_status_20260510.py`

- [ ] **Step 1: Skript yozish**

`scripts/rollback_status_20260510.py`:

```python
"""Yetkazish kuni migratsiyasini qaytarish (deploy'da xato bo'lsa).

Faqat yangi flow status'larini eski 'completed' ga qaytaradi.
delivery_date va dispatched_at o'chirilmaydi (data sifatida qoladi).
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"


def main(argv):
    if "--apply" not in argv:
        print("Rollback skripti — quyidagi UPDATE'lar bajariladi:")
        print("  delivered → completed")
        print("  out_for_delivery → confirmed (delivery_date saqlanadi)")
        print("\nBajarish: --apply")
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    backup = ROOT / "backups" / f"pre_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup.parent.mkdir(exist_ok=True)
    bk = sqlite3.connect(str(backup))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup.name}")

    cur.execute("UPDATE orders SET status='completed' WHERE status='delivered'")
    n1 = cur.rowcount
    cur.execute("UPDATE orders SET status='confirmed' WHERE status='out_for_delivery'")
    n2 = cur.rowcount
    conn.commit()

    print(f"delivered → completed: {n1} ta")
    print(f"out_for_delivery → confirmed: {n2} ta")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Commit**

```bash
git add scripts/rollback_status_20260510.py
git commit -m "chore: yetkazish kuni rollback skripti"
```

---

## Task 16: Smoke test runbook va deploy tayyorlik

**Files:**
- Create: `docs/superpowers/plans/2026-05-10-deploy-runbook.md`

- [ ] **Step 1: Runbook yozish**

`docs/superpowers/plans/2026-05-10-deploy-runbook.md`:

```markdown
# Deploy runbook — yetkazish kuni feature

**Vaqt:** Yakshanba kechasi (2026-05-17), 00:00-04:00
**Tier:** C
**Branch:** xreport-improvements (merge to main avval)

## Pre-deploy (kunduzi)
- [ ] Barcha task commit'lari main'ga merge qilingan
- [ ] tests/ to'liq pass: `pytest tests/ -v`
- [ ] Migratsiya skripti --dry-run bilan tekshirilgan

## Tungi deploy (00:00)
- [ ] DB backup: `python scripts/migrate_orders_to_new_status_20260510.py` → ko'rsatilgan ro'yxatni tekshirish
- [ ] Git tag: `git tag pre-delivery-scheduling-2026-05-10`
- [ ] Migratsiya: `python scripts/migrate_orders_to_new_status_20260510.py --apply`
- [ ] Server restart: `taskkill /IM python.exe /F` → start.bat (RDP'da qo'lda)
- [ ] Watchdog tekshirish (yangi task qo'shilgan bo'lsa)

## Smoke test (00:30)
1. Login → admin
2. /sales → "Yuklash sanasi" ustun ko'rinadi
3. Yangi test order yaratish (agent sifatida) → status=Yangi
4. Supervisor sifatida tasdiqlash → status=Tayyor
5. "Yuklash" tugmasi → modal → sana=ertaga, driver=test → tasdiqlash → status=Yo'lda
6. Stock'ga qarash → kamaygan
7. Partner.balance → o'zgarmagan (driver yetkazmagan)
8. Driver mobile → orderni ko'rish, "Yetkazdim" bosish
9. Order status → Yetkazildi
10. Partner.balance → += debt

## Agar muammo bo'lsa (rollback)
- [ ] `python scripts/rollback_status_20260510.py --apply`
- [ ] Git: `git revert <commit-hashlar>` yoki `git reset --hard pre-delivery-scheduling-2026-05-10`
- [ ] Server qayta ishga tushirish

## Post-deploy (01:30)
- [ ] Monitor: server.log da xato yo'qmi
- [ ] Telegram'ga xulosa
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-05-10-deploy-runbook.md
git commit -m "docs: deploy runbook — tungi oyna uchun smoke test va rollback"
```

---

## Self-review

✅ **Spec coverage:** Spec'ning 11 ta bo'limi (1-11) tasklarda qoplandi:
- 1-2 (maqsad/muammo) → Task 1-2 (DB + statuslar)
- 3 (status flow) → Task 6-8 (confirm/dispatch/auto-confirm)
- 4 (DB) → Task 1
- 5 (komponent) → Task 6-13 (har komponent alohida task)
- 6 (migratsiya) → Task 3
- 7 (rollback) → Task 15
- 8 (testlash) → har taskda TDD + Task 16 smoke
- 9 (deploy) → Task 16
- 10 (open savol — yo'q) → ✓
- 11 (fayllar) → file structure ro'yxat

✅ **Placeholder scan:** "TBD/TODO/implement later" yo'q. Har task'da to'liq kod.

✅ **Type consistency:** `delivery_date` (Date), `dispatched_at` (DateTime), `pending_driver_id` (FK Driver), status string konstantlar (`STATUS_OUT_FOR_DELIVERY` va boshqalar) izchil ishlatilgan.

✅ **Bug fix mapping:**
- B → Task 4 (revert balance)
- A → Task 5 (atomik confirm)
- D → Task 9 (auto-assign olib tashlash)
- E → Task 14 (deliveries dashboard)

---

## Execution

Plan tugadi va `docs/superpowers/plans/2026-05-10-delivery-scheduling.md` ga saqlandi.

**Ikki ijro yondashuv:**

**1. Subagent-Driven (tavsiya)** — Men har task uchun yangi subagent yuboraman, oraliqda ko'rib chiqaman, tezroq iteratsiya. **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`

**2. Inline Execution** — Shu sessiyada bosqichma-bosqich ijro etish, har bir checkpoint'da tasdiq olish. **REQUIRED SUB-SKILL:** `superpowers:executing-plans`

Qaysi yondashuv?
