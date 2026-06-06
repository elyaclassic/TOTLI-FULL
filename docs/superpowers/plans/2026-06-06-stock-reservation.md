# Stock Reservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `waiting_production` agent buyurtmalari o'z savatini band qilsin (FIFO seniority); band miqdorga boshqa iste'mol tegmasin — starvation (order 559) yo'qolsin.

**Architecture:** Hisoblanadigan band (status-derived, saqlanmaydi). Yangi `app/services/stock_reservation.py` moduli `waiting_production` buyurtmalardan band miqdorni hisoblaydi. Barcha iste'mol darvozalari `Stock.quantity` o'rniga `get_available_stock()` ishlatadi. Drift mumkin emas — band order statusiga bog'langan.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, pytest (in-memory DB fixtures).

**Spec:** `docs/superpowers/specs/2026-06-06-stock-reservation-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `app/services/stock_reservation.py` (YANGI) | `get_reserved_quantity` + `get_available_stock` — yagona band mantig'i |
| `tests/test_stock_reservation.py` (YANGI) | Helper unit testlari + try_confirm seniority integration |
| `app/services/agent_order_service.py` (MODIFY) | auto-dispatch band'ni hisobga olsin |
| `app/routes/sales.py` (MODIFY) | dispatch + POS confirm + POS quick-sale band'ni hisobga olsin |
| `app/routes/employees_product_purchases.py` (MODIFY) | xodim mahsulot xaridi band'ni hisobga olsin |

---

## Task 1: `stock_reservation` helper moduli (TDD)

**Files:**
- Create: `app/services/stock_reservation.py`
- Test: `tests/test_stock_reservation.py`

- [ ] **Step 1: Failing testlarni yozish**

`tests/test_stock_reservation.py`:
```python
"""Stock reservation (waiting_production band) testlari."""
from datetime import datetime


def _waiting_order(db, wh_id, pid, qty, date, number, status="waiting_production"):
    """Helper: bitta itemli waiting buyurtma yaratadi."""
    from app.models.database import Order, OrderItem
    o = Order(number=number, date=date, type="sale", source="agent",
              status=status, warehouse_id=wh_id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty))
    db.flush()
    return o


def test_no_waiting_orders_reserved_zero(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id) == 0.0


def test_reserved_sums_waiting_basket(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    _waiting_order(db, sample_warehouse.id, sample_product.id, 10, datetime(2026, 6, 4), "W1")
    _waiting_order(db, sample_warehouse.id, sample_product.id, 5, datetime(2026, 6, 5), "W2")
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id) == 15.0


def test_reserved_ignores_non_waiting_status(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    _waiting_order(db, sample_warehouse.id, sample_product.id, 7, datetime(2026, 6, 4), "C1", status="confirmed")
    _waiting_order(db, sample_warehouse.id, sample_product.id, 3, datetime(2026, 6, 4), "D1", status="draft")
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id) == 0.0


def test_before_order_excludes_self_and_newer(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    o1 = _waiting_order(db, sample_warehouse.id, sample_product.id, 10, datetime(2026, 6, 4), "W1")
    o2 = _waiting_order(db, sample_warehouse.id, sample_product.id, 5, datetime(2026, 6, 5), "W2")
    # O2 nuqtai nazaridan: faqat eski O1 (10) hisoblanadi
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id, before_order=o2) == 10.0
    # O1 nuqtai nazaridan: o'zidan eski yo'q → 0
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id, before_order=o1) == 0.0


def test_available_subtracts_reservation(db, sample_warehouse, sample_product, sample_stock):
    from app.services.stock_reservation import get_available_stock
    # sample_stock = 100
    _waiting_order(db, sample_warehouse.id, sample_product.id, 30, datetime(2026, 6, 4), "W1")
    assert get_available_stock(db, sample_warehouse.id, sample_product.id) == 70.0


def test_available_before_order_excludes_self(db, sample_warehouse, sample_product, sample_stock):
    from app.services.stock_reservation import get_available_stock
    o1 = _waiting_order(db, sample_warehouse.id, sample_product.id, 30, datetime(2026, 6, 4), "W1")
    # O1 o'z bandini iste'mol qiladi → 100 (o'zi ayirilmaydi)
    assert get_available_stock(db, sample_warehouse.id, sample_product.id, before_order=o1) == 100.0
```

- [ ] **Step 2: Testlarni ishga tushirib, fail bo'lishini tasdiqlash**

Run: `python -m pytest tests/test_stock_reservation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.stock_reservation'`

- [ ] **Step 3: Modulni yozish**

`app/services/stock_reservation.py`:
```python
"""waiting_production buyurtmalar tomonidan band qilingan stock.

Band hech qayerda SAQLANMAYDI — har safar waiting_production statusdagi
buyurtmalardan hisoblanadi. Buyurtma statusi o'zgarsa band avtomatik
yo'qoladi → drift mumkin emas.
"""
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
    """Iste'mol uchun mavjud = jismoniy qoldiq - band (seniority bo'yicha)."""
    physical = (
        db.query(func.coalesce(func.sum(Stock.quantity), 0.0))
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == product_id)
        .scalar()
    )
    reserved = get_reserved_quantity(db, warehouse_id, product_id, before_order)
    return float(physical or 0.0) - reserved
```

- [ ] **Step 4: Testlar o'tishini tasdiqlash**

Run: `python -m pytest tests/test_stock_reservation.py -v`
Expected: PASS (6 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_reservation.py tests/test_stock_reservation.py
git commit -m "feat(stock): reservation helper (get_reserved_quantity/get_available_stock)"
```

---

## Task 2: `try_confirm_waiting_orders` band'ni hisobga olsin + FIFO integration test

**Files:**
- Modify: `app/services/agent_order_service.py:57-64`
- Test: `tests/test_stock_reservation.py` (qo'shimcha)

- [ ] **Step 1: Failing integration testni qo'shish**

`tests/test_stock_reservation.py` oxiriga:
```python
def test_try_confirm_fifo_older_wins(db, sample_warehouse, sample_product):
    """2 waiting buyurtma 1 mahsulotga, stock faqat bittasiga yetadi →
    eski (date kichik) dispatch bo'ladi, yangi waiting'da qoladi."""
    from app.models.database import Stock, Driver
    from app.services.agent_order_service import try_confirm_waiting_orders

    # Stock = 10 (faqat bitta 10-lik buyurtmaga yetadi)
    db.add(Stock(warehouse_id=sample_warehouse.id, product_id=sample_product.id, quantity=10))
    db.add(Driver(code="DRV1", full_name="Driver", is_active=True))
    db.flush()

    o1 = _waiting_order(db, sample_warehouse.id, sample_product.id, 10, datetime(2026, 6, 4), "OLD")
    o2 = _waiting_order(db, sample_warehouse.id, sample_product.id, 10, datetime(2026, 6, 5), "NEW")
    o1.pending_driver_id = 1
    o2.pending_driver_id = 1
    db.commit()

    try_confirm_waiting_orders(db)
    db.refresh(o1); db.refresh(o2)

    assert o1.status == "out_for_delivery", "Eski buyurtma dispatch bo'lishi kerak"
    assert o2.status == "waiting_production", "Yangi buyurtma band tufayli kutishi kerak"
```

- [ ] **Step 2: Testni ishga tushirib, fail bo'lishini tasdiqlash**

Run: `python -m pytest tests/test_stock_reservation.py::test_try_confirm_fifo_older_wins -v`
Expected: FAIL — band hisobga olinmaydi, O2 ham dispatch bo'ladi (yoki stock 10 ikkalasiga ham "yetadi" deb ko'rinadi), assert o2 fail.

- [ ] **Step 3: `agent_order_service.py` ni o'zgartirish**

`app/services/agent_order_service.py` da, ~57-64 qatorlar. HOZIR:
```python
                stock = (
                    db.query(Stock)
                    .filter(Stock.warehouse_id == wh_id, Stock.product_id == it.product_id)
                    .first()
                )
                have = float(stock.quantity or 0) if stock else 0.0
                need = float(it.quantity or 0)
                if have + 1e-6 < need:
                    enough = False
                    break
```
GA O'ZGARTIRISH:
```python
                have = get_available_stock(db, wh_id, it.product_id, before_order=order)
                need = float(it.quantity or 0)
                if have + 1e-6 < need:
                    enough = False
                    break
```
Va fayl boshidagi importlarga qo'shish:
```python
from app.services.stock_reservation import get_available_stock
```

- [ ] **Step 4: Testlar o'tishini tasdiqlash**

Run: `python -m pytest tests/test_stock_reservation.py -v`
Expected: PASS (7 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/services/agent_order_service.py tests/test_stock_reservation.py
git commit -m "feat(stock): auto-dispatch band'ni hisobga olsin (FIFO seniority)"
```

---

## Task 3: `sales_dispatch` band'ni hisobga olsin

**Files:**
- Modify: `app/routes/sales.py:1121-1128`

- [ ] **Step 1: Joriy kodni topish**

`app/routes/sales.py` da `sales_dispatch` ichida (~1121-1128). HOZIR:
```python
    for item in items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == item.product_id,
        ).first()
        available = float(stock.quantity) if stock and stock.quantity else 0.0
        if available + 1e-6 < float(item.quantity):
```

- [ ] **Step 2: O'zgartirish**

GA:
```python
    for item in items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        available = get_available_stock(db, wh_id, item.product_id, before_order=order)
        if available + 1e-6 < float(item.quantity):
```
`sales.py` boshidagi importlarga qo'shish (agar yo'q bo'lsa):
```python
from app.services.stock_reservation import get_available_stock
```

- [ ] **Step 3: Sintaksis tekshirish**

Run: `python -m py_compile app/routes/sales.py`
Expected: xato yo'q

- [ ] **Step 4: Regressiya — to'liq test suite**

Run: `python -m pytest tests/ -q`
Expected: barcha o'tadi (yoki oldindan mavjud fail'lar o'zgarmaydi)

- [ ] **Step 5: Commit**

```bash
git add app/routes/sales.py
git commit -m "feat(stock): sales_dispatch band'ni hisobga olsin"
```

---

## Task 4: `sales_confirm` (POS) band'ni hisobga olsin

**Files:**
- Modify: `app/routes/sales.py:939-950`

- [ ] **Step 1: Joriy kodni topish**

`sales_confirm` ichida POS oqimi (~939-950). HOZIR:
```python
    insufficient = []
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == item.product_id,
        ).first()
        have = float(stock.quantity or 0) if stock else 0.0
        need = float(item.quantity or 0)
        if have + 1e-6 < need:
```

- [ ] **Step 2: O'zgartirish** (POS = yangi iste'molchi → `before_order=None`)

GA:
```python
    insufficient = []
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        have = get_available_stock(db, wh_id, item.product_id)
        need = float(item.quantity or 0)
        if have + 1e-6 < need:
```

- [ ] **Step 3: Sintaksis + test**

Run: `python -m py_compile app/routes/sales.py && python -m pytest tests/ -q`
Expected: xato yo'q, testlar o'tadi

- [ ] **Step 4: Commit**

```bash
git add app/routes/sales.py
git commit -m "feat(stock): POS sales_confirm band'ni hisobga olsin"
```

---

## Task 5: Xodim mahsulot + POS quick-sale darvozalari

**Files:**
- Modify: `app/routes/employees_product_purchases.py:264-266`
- Modify: `app/routes/sales.py:2786-2788`

- [ ] **Step 1: `employees_product_purchases.py` o'zgartirish**

HOZIR (~264-266):
```python
        stock = db.query(Stock).filter(Stock.warehouse_id == warehouse_id, Stock.product_id == pid).first()
        available = float(stock.quantity if stock else 0)
        if available + 1e-6 < qty:
```
GA:
```python
        available = get_available_stock(db, warehouse_id, pid)
        if available + 1e-6 < qty:
```
Importlarga qo'shish:
```python
from app.services.stock_reservation import get_available_stock
```

- [ ] **Step 2: `sales.py` POS quick-sale o'zgartirish** (lock SAQLANADI)

HOZIR (~2786-2788):
```python
        stock = db.query(Stock).filter(Stock.warehouse_id == wh.id, Stock.product_id == pid).with_for_update().first()
        avail = float(stock.quantity if stock else 0)
        if avail + 1e-6 < qty:
```
GA (row-lock saqlanadi, band ayriladi):
```python
        from app.services.stock_reservation import get_reserved_quantity
        stock = db.query(Stock).filter(Stock.warehouse_id == wh.id, Stock.product_id == pid).with_for_update().first()
        avail = float(stock.quantity if stock else 0) - get_reserved_quantity(db, wh.id, pid)
        if avail + 1e-6 < qty:
```

- [ ] **Step 3: Sintaksis + test**

Run: `python -m py_compile app/routes/employees_product_purchases.py app/routes/sales.py && python -m pytest tests/ -q`
Expected: xato yo'q, testlar o'tadi

- [ ] **Step 4: Commit**

```bash
git add app/routes/employees_product_purchases.py app/routes/sales.py
git commit -m "feat(stock): xodim mahsulot + POS quick-sale band'ni hisobga olsin"
```

---

## Task 6: Regressiya (559 ssenariysi) + smoke + yakun

**Files:**
- Test: `tests/test_stock_reservation.py` (qo'shimcha)

- [ ] **Step 1: 559-ssenariy regression testni qo'shish**

`tests/test_stock_reservation.py` oxiriga:
```python
def test_pos_blocked_by_agent_reservation(db, sample_warehouse, sample_product, sample_stock):
    """waiting agent buyurtma band qilgan mahsulotni POS-tekshiruv ko'rmasligi kerak.
    sample_stock=100; agent 60 band qiladi → POS uchun mavjud 40."""
    from app.services.stock_reservation import get_available_stock
    _waiting_order(db, sample_warehouse.id, sample_product.id, 60, datetime(2026, 6, 4), "AGT")
    db.commit()
    # POS yangi iste'molchi (before_order=None) → 100 - 60 = 40
    assert get_available_stock(db, sample_warehouse.id, sample_product.id) == 40.0
```

- [ ] **Step 2: To'liq test suite + smoke**

Run: `python -m pytest tests/ -q`
Expected: barcha o'tadi

Run: `python -m pytest tests/test_endpoints_smoke.py -v`
Expected: smoke endpointlar 200/303

- [ ] **Step 3: Commit**

```bash
git add tests/test_stock_reservation.py
git commit -m "test(stock): 559 starvation regression (POS band tufayli bloklanadi)"
```

- [ ] **Step 4: Deploy eslatmasi**

Bu **xulq o'zgarishi** (Tier B): POS/agent sotuv band item'larda bloklanishi mumkin — maqsadli. Deploy [[project-deploy-runbook-20260507]] bo'yicha **tungi oyna**: DB backup → main merge → server restart ([[reference-remote-restart-from-elyor]]) → post-smoke. Restart kerak (kod o'zgardi). Faza 2 (transfer/conversion + admin override + reservation UI) alohida plan.

---

## Self-Review

**Spec coverage:**
- §3.1 helper moduli → Task 1 ✓
- §3.2 FIFO seniority (before_order) → Task 1 (unit) + Task 2 (integration) ✓
- §4 Faza 1 call-site'lar: dispatch (Task 3), try_confirm (Task 2), POS confirm (Task 4), xodim mahsulot (Task 5), POS quick-sale (Task 5) ✓
- §5 edge: seniority, self-exclusion, epsilon, manfiy → Task 1/2 testlari ✓
- §6 test strategiyasi → Task 1/2/6 ✓
- §4 Faza 2 (transfer/conversion) → DOIRADAN TASHQARI (Task 6 deploy notes da alohida plan deb belgilangan) ✓

**Placeholder scan:** Yo'q — har step to'liq kod/buyruq.

**Type consistency:** `get_reserved_quantity(db, warehouse_id, product_id, before_order)` va `get_available_stock(db, warehouse_id, product_id, before_order)` barcha tasklarda bir xil imzo. `before_order` param Order obyekti (`.id`, `.date`). ✓
