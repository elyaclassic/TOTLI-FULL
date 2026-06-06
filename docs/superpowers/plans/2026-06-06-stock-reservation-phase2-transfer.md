# Stock Reservation Faza 2-A (Transfer band himoyasi) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Band qilingan (waiting_production) mahsulotni transfer/konversiya qattiq bloklasin — band qilingan tayyor mahsulot do'konga ketmasin (order 569 fix).

**Architecture:** Faza 1 `get_reserved_quantity` helperini 3 transfer/konversiya darvozasida qayta ishlatish. Yangi kichik helper `get_available_stock_at_date` (vaqt-aware stock − band) transfer confirm uchun. Hech qanday yangi saqlanadigan holat — band waiting_production buyurtmalardan hisoblanadi (drift-immune).

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, pytest (in-memory).

**Spec:** `docs/superpowers/specs/2026-06-06-stock-reservation-phase2-transfer-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `app/services/stock_reservation.py` (MODIFY) | `get_available_stock_at_date` helper qo'shish |
| `tests/test_reservation_transfer.py` (YANGI) | helper + gate-logika testlari |
| `app/routes/warehouse.py` (MODIFY) | transfer confirm + movement darvozalari band ayirsin |
| `app/routes/production_convert.py` (MODIFY) | konversiya manba darvozasi band ayirsin |

---

## Task 1: `get_available_stock_at_date` helper (TDD)

**Files:**
- Modify: `app/services/stock_reservation.py`
- Test: `tests/test_reservation_transfer.py` (yangi)

- [ ] **Step 1: Failing test yozish**

`tests/test_reservation_transfer.py`:
```python
"""Faza 2-A: transfer/konversiya band himoyasi testlari."""
from datetime import datetime


def _waiting_order(db, wh_id, pid, qty, date, number):
    from app.models.database import Order, OrderItem
    o = Order(number=number, date=date, type="sale", source="agent",
              status="waiting_production", warehouse_id=wh_id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty))
    db.flush()
    return o


def test_available_at_date_no_cutoff_subtracts_reservation(db, sample_warehouse, sample_product, sample_stock):
    """cutoff=None → joriy stock − band."""
    from app.services.stock_reservation import get_available_stock_at_date
    _waiting_order(db, sample_warehouse.id, sample_product.id, 30, datetime(2026, 6, 4), "W1")
    # sample_stock=100, band=30 → 70
    assert get_available_stock_at_date(db, sample_warehouse.id, sample_product.id) == 70.0


def test_available_at_date_no_reservation_equals_physical(db, sample_warehouse, sample_product, sample_stock):
    """Band yo'q bo'lsa → jismoniy qoldiq (xulq o'zgarmaydi)."""
    from app.services.stock_reservation import get_available_stock_at_date
    assert get_available_stock_at_date(db, sample_warehouse.id, sample_product.id) == 100.0
```

- [ ] **Step 2: Run, FAIL**

Run: `python -m pytest tests/test_reservation_transfer.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_available_stock_at_date'`.

- [ ] **Step 3: Helper qo'shish**

`app/services/stock_reservation.py` oxiriga qo'shish:
```python
def get_available_stock_at_date(db, warehouse_id, product_id, cutoff=None) -> float:
    """Berilgan sanadagi (cutoff) mavjud stock − band. cutoff=None → joriy qoldiq.

    Transfer (vaqt-aware) darvozalari uchun: get_stock_at_date sanagacha qoldiqni
    beradi, undan joriy band (waiting_production) ayriladi.
    """
    from app.utils.stock_at_date import get_stock_at_date
    physical = get_stock_at_date(db, warehouse_id, product_id, cutoff=cutoff)
    return float(physical or 0.0) - get_reserved_quantity(db, warehouse_id, product_id)
```

- [ ] **Step 4: Run, PASS**

Run: `python -m pytest tests/test_reservation_transfer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_reservation.py tests/test_reservation_transfer.py
git commit -m "feat(stock): get_available_stock_at_date helper (Faza 2-A)"
```

---

## Task 2: warehouse.py — transfer confirm + movement darvozalari

**Files:**
- Modify: `app/routes/warehouse.py` (~653-664 transfer confirm, ~822-835 movement)

- [ ] **Step 1: Transfer confirm darvozasi (~653)**

FIND:
```python
    for item in items:
        need = float(item.quantity or 0)
        have = get_stock_at_date(db, transfer.from_warehouse_id, item.product_id, cutoff=_cutoff)
        if have + 1e-6 < need:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            name = prod.name if prod else f"#{item.product_id}"
            avail_display = "0" if abs(have) < 1e-6 else ("%.6f" % have).rstrip("0").rstrip(".")
            date_hint = f" ({transfer.date.strftime('%d.%m.%Y')} sanasida)" if _cutoff else ""
            return RedirectResponse(
                url=f"/warehouse/transfers/{transfer_id}?error=" + quote(f"Qayerdan omborda «{name}» yetarli emas (kerak: {item.quantity}, mavjud: {avail_display}{date_hint})"),
                status_code=303,
            )
```
REPLACE WITH:
```python
    from app.services.stock_reservation import get_available_stock_at_date, get_reserved_quantity
    for item in items:
        need = float(item.quantity or 0)
        have = get_available_stock_at_date(db, transfer.from_warehouse_id, item.product_id, cutoff=_cutoff)
        if have + 1e-6 < need:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            name = prod.name if prod else f"#{item.product_id}"
            reserved = get_reserved_quantity(db, transfer.from_warehouse_id, item.product_id)
            avail_display = "0" if abs(have) < 1e-6 else ("%.6f" % have).rstrip("0").rstrip(".")
            date_hint = f" ({transfer.date.strftime('%d.%m.%Y')} sanasida)" if _cutoff else ""
            res_hint = f", {reserved:g} band (waiting buyurtmalar)" if reserved > 1e-6 else ""
            return RedirectResponse(
                url=f"/warehouse/transfers/{transfer_id}?error=" + quote(f"Qayerdan omborda «{name}» yetarli emas (kerak: {item.quantity}, mavjud: {avail_display}{res_hint}{date_hint})"),
                status_code=303,
            )
```

- [ ] **Step 2: Movement darvozasi (~822)**

FIND:
```python
    source = db.query(Stock).filter(
        Stock.warehouse_id == from_warehouse_id,
        Stock.product_id == product_id,
    ).first()
    need_q = float(quantity or 0)
    have_q = float(source.quantity or 0) if source else 0
    if not source or (have_q + 1e-6 < need_q):
        product = db.query(Product).filter(Product.id == product_id).first()
        name = product.name if product else f"#{product_id}"
        avail_display = "0" if abs(have_q) < 1e-6 else ("%.6f" % have_q).rstrip("0").rstrip(".")
        return RedirectResponse(
            url="/warehouse/movement?error=1&detail=" + quote(f"Qayerdan omborda «{name}» yetarli emas (kerak: {quantity}, mavjud: {avail_display})"),
            status_code=303,
        )
```
REPLACE WITH:
```python
    from app.services.stock_reservation import get_reserved_quantity
    source = db.query(Stock).filter(
        Stock.warehouse_id == from_warehouse_id,
        Stock.product_id == product_id,
    ).first()
    need_q = float(quantity or 0)
    reserved_q = get_reserved_quantity(db, from_warehouse_id, product_id)
    have_q = (float(source.quantity or 0) if source else 0) - reserved_q
    if not source or (have_q + 1e-6 < need_q):
        product = db.query(Product).filter(Product.id == product_id).first()
        name = product.name if product else f"#{product_id}"
        avail_display = "0" if abs(have_q) < 1e-6 else ("%.6f" % have_q).rstrip("0").rstrip(".")
        res_hint = f", {reserved_q:g} band (waiting buyurtmalar)" if reserved_q > 1e-6 else ""
        return RedirectResponse(
            url="/warehouse/movement?error=1&detail=" + quote(f"Qayerdan omborda «{name}» yetarli emas (kerak: {quantity}, mavjud: {avail_display}{res_hint})"),
            status_code=303,
        )
```

- [ ] **Step 3: Sintaksis + regressiya**

Run: `python -m py_compile app/routes/warehouse.py && python -m pytest tests/ -q`
Expected: xato yo'q; faqat oldindan ma'lum `test_login_get_returns_200` fail (boshqa fail bo'lsa STOP).

- [ ] **Step 4: Commit**

```bash
git add app/routes/warehouse.py
git commit -m "feat(stock): transfer + movement band'ni hisobga olsin (Faza 2-A)"
```

---

## Task 3: production_convert.py — konversiya manba darvozasi

**Files:**
- Modify: `app/routes/production_convert.py` (~204-217)

- [ ] **Step 1: Konversiya darvozasi (lock SAQLANADI)**

FIND:
```python
    source_stock = (
        db.query(Stock)
        .filter(Stock.warehouse_id == source_warehouse_id, Stock.product_id == source_product_id)
        .with_for_update()
        .first()
    )
    have = float(source_stock.quantity or 0) if source_stock else 0.0
    if have + 1e-6 < source_units:
        unit_label = "dona" if is_piece else "kg"
        return RedirectResponse(
            url="/production/convert?error=stock&detail=" + quote(
                f"Manba omborda yetmaydi: {source.name} kerak {source_units} {unit_label}, bor {have} {unit_label}"
            ),
            status_code=303,
        )
```
REPLACE WITH:
```python
    from app.services.stock_reservation import get_reserved_quantity
    source_stock = (
        db.query(Stock)
        .filter(Stock.warehouse_id == source_warehouse_id, Stock.product_id == source_product_id)
        .with_for_update()
        .first()
    )
    reserved = get_reserved_quantity(db, source_warehouse_id, source_product_id)
    have = (float(source_stock.quantity or 0) if source_stock else 0.0) - reserved
    if have + 1e-6 < source_units:
        unit_label = "dona" if is_piece else "kg"
        res_hint = f", {reserved:g} band (waiting buyurtmalar)" if reserved > 1e-6 else ""
        return RedirectResponse(
            url="/production/convert?error=stock&detail=" + quote(
                f"Manba omborda yetmaydi: {source.name} kerak {source_units} {unit_label}, bor {have} {unit_label}{res_hint}"
            ),
            status_code=303,
        )
```

- [ ] **Step 2: Sintaksis + regressiya**

Run: `python -m py_compile app/routes/production_convert.py && python -m pytest tests/ -q`
Expected: xato yo'q; faqat oldindan ma'lum login fail.

- [ ] **Step 3: Commit**

```bash
git add app/routes/production_convert.py
git commit -m "feat(stock): konversiya manba band'ni hisobga olsin (Faza 2-A)"
```

---

## Task 4: Regressiya test (order 569 ssenariysi) + yakun

**Files:**
- Test: `tests/test_reservation_transfer.py` (qo'shimcha)

- [ ] **Step 1: Gate-logika regression test qo'shish**

`tests/test_reservation_transfer.py` oxiriga:
```python
def test_transfer_blocked_when_all_reserved(db, sample_warehouse, sample_product, sample_stock):
    """Order 569 ssenariysi: butun stock band → transfer uchun mavjud 0 (bloklanadi)."""
    from app.services.stock_reservation import get_available_stock_at_date
    _waiting_order(db, sample_warehouse.id, sample_product.id, 100, datetime(2026, 6, 4), "AGT")
    # sample_stock=100, band=100 → transfer uchun 0
    avail = get_available_stock_at_date(db, sample_warehouse.id, sample_product.id)
    assert avail == 0.0
    # 1 dona transfer ham bloklanishi kerak: avail + 1e-6 < 1
    assert avail + 1e-6 < 1.0


def test_transfer_allowed_for_unreserved_surplus(db, sample_warehouse, sample_product, sample_stock):
    """Qisman band: 100 stock, 60 band → 40 transfer qilsa bo'ladi, 41 bo'lmaydi."""
    from app.services.stock_reservation import get_available_stock_at_date
    _waiting_order(db, sample_warehouse.id, sample_product.id, 60, datetime(2026, 6, 4), "AGT")
    avail = get_available_stock_at_date(db, sample_warehouse.id, sample_product.id)
    assert avail == 40.0
    assert not (avail + 1e-6 < 40.0)   # 40 o'tadi
    assert avail + 1e-6 < 41.0          # 41 bloklanadi
```

- [ ] **Step 2: To'liq suite**

Run: `python -m pytest tests/test_reservation_transfer.py -v` → expect 4 passed.
Run: `python -m pytest tests/ -q` → expect faqat oldindan ma'lum login fail.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reservation_transfer.py
git commit -m "test(stock): transfer band regression (order 569 ssenariysi)"
```

- [ ] **Step 4: Deploy eslatmasi**

Tier B xulq o'zgarishi: band mahsulot transfer/konversiya bloklanadi. Deploy [[project-deploy-runbook-20260507]]: backup → main merge → restart ([[reference-remote-restart-from-elyor]]) → post-smoke. Deploy paytida 0 waiting bo'lsa darhol ta'sir yo'q. B (admin override) va C (UI) keyingi bo'laklar.

---

## Self-Review

**Spec coverage:**
- §4 transfer confirm → Task 2 Step 1 ✓; movement → Task 2 Step 2 ✓; konversiya → Task 3 ✓
- §5 xato xabari (band ko'rsatish) → har gate'da res_hint ✓
- §6 edge: band=0 (xulq o'zgarmaydi) → Task 1 test ✓; back-dated cutoff → get_available_stock_at_date cutoff param ✓; lock saqlash → Task 3 lock qoldi ✓
- §7 test → Task 1 + Task 4 ✓

**Placeholder scan:** Yo'q — har step to'liq kod.

**Type consistency:** `get_available_stock_at_date(db, warehouse_id, product_id, cutoff=None)` va `get_reserved_quantity(db, warehouse_id, product_id)` barcha tasklarda bir xil imzo. ✓
