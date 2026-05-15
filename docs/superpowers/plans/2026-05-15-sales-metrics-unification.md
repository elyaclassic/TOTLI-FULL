# Sales-metrics yagona helper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sotuv "qaysi buyurtma sanaladi" ta'rifini bitta modulga (`app/services/sales_metrics.py`) qulflab, 4 endpoint shundan foydalanadi.

**Architecture:** `finance_service.cash_balance_formula()` etalon uslubi — ta'rif (status to'plami + `Order.date`) yagona modulda; har endpoint qaytgan SQLAlchemy `Query`'ni o'z shakliga moslab kengaytiradi (paginatsiya / JOIN / agregatsiya). Faqat read yo'llari — schema/migratsiya/mutatsiya yo'q.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest (in-memory SQLite, `tests/conftest.py` `db` fixture).

**Spec:** `docs/superpowers/specs/2026-05-15-sales-metrics-unification-design.md`

---

## File Structure

- **Create:** `app/services/sales_metrics.py` — yagona ta'rif: `SALE_REALIZED`, `sale_orders_query()`, `sale_revenue()`.
- **Create:** `tests/test_sales_metrics.py` — helper unit testlari + reconciliation invariant.
- **Create:** `scripts/sales_metrics_snapshot.py` — deploy oldidan/keyin raqam delta prognoz/tasdiq.
- **Modify:** `app/routes/reports.py` — `_compute_sales_and_cogs` (profit), `sold_products_report`, `report_sales`.
- **Modify:** `app/routes/sales.py` — `sales_list` (realized konstanta + "Qoralama" yorlig'i).
- **Modify:** `app/templates/reports/sales.html` — cancelled qator kulrang + badge.

---

## Task 1: `sales_metrics` modul + unit testlar (TDD)

**Files:**
- Create: `app/services/sales_metrics.py`
- Test: `tests/test_sales_metrics.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_sales_metrics.py`:

```python
from datetime import datetime

import pytest

from app.models.database import Order
from app.services.sales_metrics import (
    SALE_REALIZED,
    sale_orders_query,
    sale_revenue,
)


def _order(db, *, status, total, date, type_="sale", warehouse_id=None, partner_id=None):
    o = Order(
        type=type_, status=status, total=total, date=date,
        warehouse_id=warehouse_id, partner_id=partner_id,
        number=f"T-{status}-{int(total)}-{date:%Y%m%d%H%M%S}",
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def test_realized_includes_only_three_statuses(db):
    d = datetime(2026, 5, 10)
    for st in ("delivered", "completed", "confirmed"):
        _order(db, status=st, total=100, date=d)
    for st in ("draft", "cancelled", "waiting_production", "out_for_delivery", "pending"):
        _order(db, status=st, total=999, date=d)
    rows = sale_orders_query(
        db, scope="realized", dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
    ).all()
    assert sorted(o.status for o in rows) == ["completed", "confirmed", "delivered"]


def test_all_scope_includes_cancelled(db):
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=100, date=d)
    _order(db, status="cancelled", total=50, date=d)
    rows = sale_orders_query(
        db, scope="all", dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
    ).all()
    assert len(rows) == 2


def test_non_sale_type_excluded(db):
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=100, date=d)
    _order(db, status="completed", total=70, date=d, type_="return_sale")
    assert sale_revenue(db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)) == 100.0


def test_revenue_sums_realized_total(db):
    d = datetime(2026, 5, 10)
    _order(db, status="delivered", total=100, date=d)
    _order(db, status="confirmed", total=200, date=d)
    _order(db, status="cancelled", total=999, date=d)
    _order(db, status="draft", total=999, date=d)
    assert sale_revenue(db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)) == 300.0


def test_date_boundary_inclusive(db):
    _order(db, status="completed", total=10, date=datetime(2026, 5, 1, 0, 0, 0))
    _order(db, status="completed", total=20, date=datetime(2026, 5, 31, 23, 59, 59))
    _order(db, status="completed", total=99, date=datetime(2026, 6, 1, 0, 0, 0))
    assert sale_revenue(
        db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31, 23, 59, 59)
    ) == 30.0


def test_warehouse_filter(db):
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=100, date=d, warehouse_id=1)
    _order(db, status="completed", total=200, date=d, warehouse_id=2)
    assert sale_revenue(
        db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31), warehouse_id=1
    ) == 100.0


def test_empty_range_returns_zero(db):
    assert sale_revenue(
        db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
    ) == 0.0


def test_unknown_scope_raises(db):
    with pytest.raises(ValueError):
        sale_orders_query(
            db, scope="bogus", dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
        )


def test_realized_constant_is_exactly_three(db):
    assert set(SALE_REALIZED) == {"delivered", "completed", "confirmed"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sales_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.sales_metrics'`

- [ ] **Step 3: Write the module**

`app/services/sales_metrics.py`:

```python
"""Sotuv metrikalari — YAGONA HAQIQAT MANBAI.

Tizimda "sotuv summasi" 4 endpoint'da 4 xil hisoblanardi (status/sana drift).
Bu modul ta'rifni bitta joyga qulflaydi. finance_service.cash_balance_formula
etalon uslubi: ta'rif shu yerda, shakl (paginatsiya/JOIN/agregat) endpoint'da.
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.database import Order

# Daromad/foyda hisoblanadigan sotuv holatlari — YAGONA ta'rif.
# Modul tashqarisida Order.status.in_(...) yozilmaydi.
SALE_REALIZED = ("delivered", "completed", "confirmed")


def sale_orders_query(
    db: Session,
    *,
    scope: str = "realized",
    dt_from=None,
    dt_to=None,
    warehouse_id: Optional[int] = None,
    partner_id: Optional[int] = None,
) -> Query:
    """type=='sale' Order query'si. Sana doimo Order.date (biznes sanasi).

    scope='realized' -> status IN SALE_REALIZED
    scope='all'      -> status filtri yo'q (cancelled ham; operatsion ro'yxat)

    Qaytgan Query'ni endpoint o'zi kengaytiradi (paginate/JOIN/agregat).
    """
    if scope not in ("realized", "all"):
        raise ValueError(f"noma'lum scope: {scope!r}")
    q = db.query(Order).filter(Order.type == "sale")
    if scope == "realized":
        q = q.filter(Order.status.in_(SALE_REALIZED))
    if dt_from is not None:
        q = q.filter(Order.date >= dt_from)
    if dt_to is not None:
        q = q.filter(Order.date <= dt_to)
    if warehouse_id:
        q = q.filter(Order.warehouse_id == warehouse_id)
    if partner_id:
        q = q.filter(Order.partner_id == partner_id)
    return q


def sale_revenue(
    db: Session,
    *,
    dt_from,
    dt_to,
    warehouse_id: Optional[int] = None,
    partner_id: Optional[int] = None,
) -> float:
    """realized scope bo'yicha Sum(Order.total) — bitta skalyar."""
    q = sale_orders_query(
        db,
        scope="realized",
        dt_from=dt_from,
        dt_to=dt_to,
        warehouse_id=warehouse_id,
        partner_id=partner_id,
    )
    val = q.with_entities(func.coalesce(func.sum(Order.total), 0)).scalar()
    return float(val or 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sales_metrics.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/sales_metrics.py tests/test_sales_metrics.py
git commit -m "feat(sales-metrics): yagona sotuv ta'rifi moduli + testlar"
```

---

## Task 2: `/reports/profit` helper'ga ulanadi

**Files:**
- Modify: `app/routes/reports.py` — `_compute_sales_and_cogs` (~2389-2410)
- Test: `tests/test_sales_metrics.py` (yangi test qo'shiladi)

- [ ] **Step 1: Write the failing test**

`tests/test_sales_metrics.py` oxiriga qo'shing:

```python
def test_profit_compute_uses_realized_scope(db):
    from app.routes.reports import _compute_sales_and_cogs
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=500, date=d)
    _order(db, status="confirmed", total=300, date=d)
    _order(db, status="draft", total=999, date=d)        # realized emas
    _order(db, status="cancelled", total=999, date=d)    # realized emas
    sale_orders, revenue, cogs, sale_items = _compute_sales_and_cogs(
        db, datetime(2026, 5, 1), datetime(2026, 5, 31, 23, 59, 59)
    )
    assert revenue == 800.0
    assert {o.status for o in sale_orders} == {"completed", "confirmed"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sales_metrics.py::test_profit_compute_uses_realized_scope -v`
Expected: FAIL — `revenue == 1799.0` (hozir `status != cancelled` draft'ni ham oladi)

- [ ] **Step 3: Modify `_compute_sales_and_cogs`**

`app/routes/reports.py`, hozirgi (~2391-2396):

```python
    sale_orders = (
        db.query(Order)
        .filter(Order.type == "sale", Order.status != "cancelled",
                Order.date >= dt_from, Order.date <= dt_to)
        .all()
    )
```

bilan almashtiring:

```python
    from app.services.sales_metrics import sale_orders_query
    sale_orders = sale_orders_query(
        db, scope="realized", dt_from=dt_from, dt_to=dt_to
    ).all()
```

(Qolgan kod — `revenue`, `cogs`, `sale_items` — o'zgarmaydi. `return_sale` qaytarish bloki `report_profit` ichida alohida, unga tegilmaydi.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sales_metrics.py -v`
Expected: PASS — barcha testlar (10 passed)

- [ ] **Step 5: Commit**

```bash
git add app/routes/reports.py tests/test_sales_metrics.py
git commit -m "fix(profit): daromad realized scope (draft/waiting chiqdi)"
```

---

## Task 3: `/reports/sold-products` realized scope + `Order.date`

**Files:**
- Modify: `app/routes/reports.py` — `sold_products_report` (status/sana filtri, 2 joy: asosiy `q` ~2631-2636 va `discount_q` ~2650-2655)

- [ ] **Step 1: Write the failing test**

`tests/test_sales_metrics.py` oxiriga qo'shing:

```python
def test_sold_products_status_filter_is_realized(db):
    import inspect
    from app.routes import reports
    src = inspect.getsource(reports.sold_products_report)
    # Eski literal status/created_at filtri qolmasligi kerak
    assert 'Order.status.in_(("completed", "delivered"))' not in src
    assert "Order.created_at >= d_from" not in src
    assert "Order.created_at <= d_to" not in src
    # Yangi: SALE_REALIZED va Order.date ishlatiladi
    assert "SALE_REALIZED" in src
    assert "Order.date >= d_from" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sales_metrics.py::test_sold_products_status_filter_is_realized -v`
Expected: FAIL — eski `Order.status.in_(("completed", "delivered"))` hali mavjud

- [ ] **Step 3: Modify `sold_products_report`**

`app/routes/reports.py`, funksiya boshida (`sold_products_report` ichida, `try:` bloklaridan keyin yoki funksiya tepasida) importni qo'shing:

```python
    from app.services.sales_metrics import SALE_REALIZED
```

Asosiy `q` filtri — hozirgi:

```python
        .filter(
            Order.type == "sale",
            Order.status.in_(("completed", "delivered")),
            Order.created_at >= d_from,
            Order.created_at <= d_to,
        )
```

bilan almashtiring:

```python
        .filter(
            Order.type == "sale",
            Order.status.in_(SALE_REALIZED),
            Order.date >= d_from,
            Order.date <= d_to,
        )
```

`discount_q` filtri — hozirgi:

```python
        .filter(
            Order.type == "sale",
            Order.status.in_(("completed", "delivered")),
            Order.created_at >= d_from,
            Order.created_at <= d_to,
        )
```

bilan almashtiring (aynan bir xil yangi blok):

```python
        .filter(
            Order.type == "sale",
            Order.status.in_(SALE_REALIZED),
            Order.date >= d_from,
            Order.date <= d_to,
        )
```

(Per-product item-level sum, chegirma ratio, `grand_*` hisob — o'zgarmaydi. Bu ataylab: sold-products mahsulot tahlili, spec §4 "ma'lum farq".)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sales_metrics.py -v`
Expected: PASS — barcha testlar (11 passed)

- [ ] **Step 5: Commit**

```bash
git add app/routes/reports.py tests/test_sales_metrics.py
git commit -m "fix(sold-products): realized scope + Order.date (created_at o'rniga)"
```

---

## Task 4: `/reports/sales` — ro'yxat `all`, total realized + template

**Files:**
- Modify: `app/routes/reports.py` — `report_sales` (~112-124)
- Modify: `app/templates/reports/sales.html` (~99-115)

- [ ] **Step 1: Write the failing test**

`tests/test_sales_metrics.py` oxiriga qo'shing:

```python
def test_report_sales_total_excludes_cancelled(db, monkeypatch):
    from app.routes import reports
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=1000, date=d)
    _order(db, status="cancelled", total=400, date=d)

    captured = {}

    def fake_tpl(name, ctx):
        captured.update(ctx)
        return "ok"

    monkeypatch.setattr(reports.templates, "TemplateResponse", fake_tpl)

    class _U:
        role = "admin"

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        reports.report_sales(
            request=None, start_date="2026-05-01", end_date="2026-05-31",
            warehouse_id=None, partner_id=None, db=db, current_user=_U(),
        )
    )
    # Ro'yxat cancelled'ni ham ko'rsatadi (audit), total faqat realized
    assert len(captured["orders"]) == 2
    assert captured["total"] == 1000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sales_metrics.py::test_report_sales_total_excludes_cancelled -v`
Expected: FAIL — `captured["total"] == 1400.0` (hozir cancelled ham qo'shiladi)

- [ ] **Step 3: Modify `report_sales`**

`app/routes/reports.py`, hozirgi (~112-124):

```python
    q = db.query(Order).filter(
        Order.type == "sale",
        Order.date >= start_date,
        Order.date <= end_date + " 23:59:59",
    )
    if warehouse_id:
        q = q.filter(Order.warehouse_id == warehouse_id)
    if partner_id:
        q = q.filter(Order.partner_id == partner_id)
    orders = q.all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name).all()
    partners = db.query(Partner).filter(Partner.type.in_(["customer", "both"])).order_by(Partner.name).all()
    total = sum(o.total or 0 for o in orders)
```

bilan almashtiring:

```python
    from app.services.sales_metrics import sale_orders_query, sale_revenue
    dt_from = start_date
    dt_to = end_date + " 23:59:59"
    orders = (
        sale_orders_query(
            db, scope="all", dt_from=dt_from, dt_to=dt_to,
            warehouse_id=warehouse_id, partner_id=partner_id,
        )
        .order_by(Order.date.desc())
        .all()
    )
    warehouses = db.query(Warehouse).order_by(Warehouse.name).all()
    partners = db.query(Partner).filter(Partner.type.in_(["customer", "both"])).order_by(Partner.name).all()
    total = sale_revenue(
        db, dt_from=dt_from, dt_to=dt_to,
        warehouse_id=warehouse_id, partner_id=partner_id,
    )
```

- [ ] **Step 4: Modify template — cancelled qatorni kulrang qiling**

`app/templates/reports/sales.html`, hozirgi (~100):

```html
                        <tr>
```

bilan almashtiring:

```html
                        <tr{% if order.status == 'cancelled' %} class="text-muted" style="opacity:.55;text-decoration:line-through"{% endif %}>
```

Hozirgi status katak (~108-114):

```html
                                {% if order.status == 'completed' %}
                                    <span class="badge-done">Bajarildi</span>
                                {% elif order.status == 'draft' %}
                                    <span class="badge-draft">Qoralama</span>
                                {% else %}
                                    <span class="badge-inactive">{{ order.status }}</span>
                                {% endif %}
```

bilan almashtiring:

```html
                                {% if order.status == 'completed' %}
                                    <span class="badge-done">Bajarildi</span>
                                {% elif order.status == 'draft' %}
                                    <span class="badge-draft">Qoralama</span>
                                {% elif order.status == 'cancelled' %}
                                    <span class="badge-cancelled">Bekor qilingan</span>
                                {% else %}
                                    <span class="badge-inactive">{{ order.status }}</span>
                                {% endif %}
```

- [ ] **Step 5: Run tests + manual check**

Run: `python -m pytest tests/test_sales_metrics.py -v`
Expected: PASS — barcha testlar (12 passed)

- [ ] **Step 6: Commit**

```bash
git add app/routes/reports.py app/templates/reports/sales.html tests/test_sales_metrics.py
git commit -m "fix(reports/sales): total realized, cancelled ro'yxatda kulrang"
```

---

## Task 5: `/sales` — realized konstanta + haqiqiy "Qoralama"

**Files:**
- Modify: `app/routes/sales.py` — `sales_list` (status literal'lari: 160, 177, 205, 224; draft_count: 171)

- [ ] **Step 1: Write the failing test**

`tests/test_sales_metrics.py` oxiriga qo'shing:

```python
def test_sales_list_uses_shared_constant_no_literal(db):
    import inspect
    from app.routes import sales
    src = inspect.getsource(sales.sales_list)
    assert 'SALE_REALIZED' in src
    # Eski qo'lda yozilgan status ro'yxati qolmasligi kerak
    assert '["completed", "delivered", "confirmed"]' not in src
    # "Qoralama" endi haqiqiy draft soni — total_count ayirmasi emas
    assert 'pg["total_count"] - completed_count' not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sales_metrics.py::test_sales_list_uses_shared_constant_no_literal -v`
Expected: FAIL — eski literal `["completed", "delivered", "confirmed"]` mavjud

- [ ] **Step 3: Modify `sales_list`**

`app/routes/sales.py`, `sales_list` funksiyasi ichida (mavjud `from sqlalchemy import func as sa_func` qatoridan keyin, ~153):

```python
    from sqlalchemy import func as sa_func
```

dan keyin qo'shing:

```python
    from app.services.sales_metrics import SALE_REALIZED
```

Quyidagi 4 ta qatorning HAR BIRINI (asl: `Order.status.in_(["completed", "delivered", "confirmed"]),`) shu bilan almashtiring:

```python
        Order.status.in_(SALE_REALIZED),
```

(Joylar: `stats_row` filtri ~160; `pay_stats` filtri ~177; `chg_q` filtri ~205; `tnx_q` filtri ~224. Indentatsiya har joyda asl qatorga mos bo'lsin.)

Haqiqiy "Qoralama" — hozirgi (~171):

```python
    draft_count = pg["total_count"] - completed_count
```

bilan almashtiring:

```python
    draft_q = db.query(sa_func.count(Order.id)).filter(
        Order.type == "sale", Order.status == "draft"
    )
    if date_from and date_from.strip():
        draft_q = draft_q.filter(Order.date >= date_from.strip()[:10] + " 00:00:00")
    if date_to and date_to.strip():
        draft_q = draft_q.filter(Order.date <= date_to.strip()[:10] + " 23:59:59")
    if wh_id is not None and wh_id > 0:
        draft_q = draft_q.filter(Order.warehouse_id == wh_id)
    draft_count = int(draft_q.scalar() or 0)
```

- [ ] **Step 4: Run tests + smoke**

Run: `python -m pytest tests/test_sales_metrics.py -v`
Expected: PASS — barcha testlar (13 passed)

Run: `python -m pytest tests/test_endpoints_smoke.py -v`
Expected: PASS (regress yo'q)

- [ ] **Step 5: Commit**

```bash
git add app/routes/sales.py tests/test_sales_metrics.py
git commit -m "fix(sales): SALE_REALIZED konstanta + haqiqiy Qoralama soni"
```

---

## Task 6: Reconciliation invariant testi

**Files:**
- Test: `tests/test_sales_metrics.py` (yangi test)

- [ ] **Step 1: Write the test**

`tests/test_sales_metrics.py` oxiriga qo'shing:

```python
def test_reconciliation_invariant_sales_equals_revenue(db):
    """Buzilgan invariant: /sales jami summa == sale_revenue == Sum(realized total).

    Refactordan keyin uchchalasi bir davr/filtr uchun teng bo'lishi shart.
    """
    d = datetime(2026, 5, 10)
    _order(db, status="delivered", total=1000, date=d)
    _order(db, status="completed", total=500, date=d)
    _order(db, status="confirmed", total=250, date=d)
    _order(db, status="draft", total=777, date=d)
    _order(db, status="cancelled", total=888, date=d)

    dt_from, dt_to = datetime(2026, 5, 1), datetime(2026, 5, 31, 23, 59, 59)

    rev = sale_revenue(db, dt_from=dt_from, dt_to=dt_to)
    realized_sum = sum(
        o.total
        for o in sale_orders_query(db, scope="realized", dt_from=dt_from, dt_to=dt_to).all()
    )
    assert rev == realized_sum == 1750.0
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_sales_metrics.py::test_reconciliation_invariant_sales_equals_revenue -v`
Expected: PASS (Task 1-5 tugagach invariant ushlanadi)

- [ ] **Step 3: Commit**

```bash
git add tests/test_sales_metrics.py
git commit -m "test(sales-metrics): reconciliation invariant"
```

---

## Task 7: Before/after snapshot skripti

**Files:**
- Create: `scripts/sales_metrics_snapshot.py`

- [ ] **Step 1: Write the script**

`scripts/sales_metrics_snapshot.py`:

```python
"""Sotuv summasi formula variantlari snapshot — deploy delta prognoz/tasdiq.

DB o'zgarmaydi (faqat kod o'zgaradi), shuning uchun bu skript bir vaqtning
o'zida ESKI va YANGI formulalarni hisoblab, kutilgan deltani ko'rsatadi.
Deploy oldidan ishga tushiring, kutilgan deltani yozib oling; deploy keyin
hisobotlardagi raqamlar shu YANGI ustunga mos kelishini tasdiqlang.

Ishlatish:
    python scripts/sales_metrics_snapshot.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.models.database import Order

PERIODS = [
    ("Joriy oy (01..bugun)", datetime.now().replace(day=1, hour=0, minute=0, second=0),
     datetime.now().replace(hour=23, minute=59, second=59)),
    ("2026-05-01..2026-05-15", datetime(2026, 5, 1), datetime(2026, 5, 15, 23, 59, 59)),
]


def _sum(q):
    return float(q.with_entities(func.coalesce(func.sum(Order.total), 0)).scalar() or 0)


def main():
    engine = create_engine("sqlite:///totli_holva.db")
    db = sessionmaker(bind=engine)()
    try:
        for label, a, b in PERIODS:
            base = db.query(Order).filter(Order.type == "sale", Order.date >= a, Order.date <= b)
            new_realized = _sum(base.filter(Order.status.in_(("delivered", "completed", "confirmed"))))
            old_all = _sum(base)
            old_non_cancelled = _sum(base.filter(Order.status != "cancelled"))
            print(f"\n=== {label} ===")
            print(f"  YANGI realized (sales/profit/savdo total): {new_realized:>18,.0f}")
            print(f"  ESKI savdo total (hammasi, cancelled ham):  {old_all:>18,.0f}"
                  f"   delta {new_realized - old_all:>+15,.0f}")
            print(f"  ESKI profit revenue (status != cancelled):  {old_non_cancelled:>18,.0f}"
                  f"   delta {new_realized - old_non_cancelled:>+15,.0f}")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script (read-only, live DB)**

Run: `python scripts/sales_metrics_snapshot.py`
Expected: Har davr uchun YANGI realized va ESKI variantlar + delta chiqadi (xato yo'q). Deltani spec §4 bilan solishtiring — tushuntirib bo'lmaydigan delta = to'xta.

- [ ] **Step 3: Commit**

```bash
git add scripts/sales_metrics_snapshot.py
git commit -m "chore(sales-metrics): deploy delta snapshot skripti"
```

---

## Deploy (spec §6)

Tungi oyna (00:00–04:00). Branch `safe-fix-sales-metrics` ← `main`.

1. `git tag pre-sales-metrics-$(date +%Y%m%d)` + DB dump
2. `python scripts/sales_metrics_snapshot.py` → eski/kutilgan raqamlarni yozib ol
3. `python -m pytest tests/test_sales_metrics.py tests/test_endpoints_smoke.py -v` → hammasi PASS
4. merge → `taskkill //IM python.exe //F` → `start.bat`
5. Post-smoke: 4 sahifa ochiladi (xato yo'q); `python scripts/sales_metrics_snapshot.py` qayta → hisobot raqamlari YANGI ustunga mos
6. Rollback (kerak bo'lsa): `git revert <merge>` + restart (~1 daq, ma'lumot xavfi 0)

---

## Self-Review natijasi

- **Spec coverage:** §2 ta'riflar → Task 1 (`SALE_REALIZED`, `Order.date`); §3 modul → Task 1; §4 har endpoint → Task 2 (profit), 3 (sold-products), 4 (savdo + cancelled UX), 5 (/sales + Qoralama); §5 test → Task 1/6 (unit+reconciliation), Task 7 (snapshot); §6 deploy → Deploy bo'limi. Gap yo'q.
- **Placeholder scan:** TBD/TODO yo'q; har step to'liq kod/komanda.
- **Type consistency:** `sale_orders_query`/`sale_revenue`/`SALE_REALIZED` nomi va imzosi Task 1-7 bo'ylab bir xil; `scope` qiymatlari faqat `"realized"`/`"all"`.
