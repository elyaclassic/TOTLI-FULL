# Stock Reservation Faza 2-C (Reservation UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qoldiq hisobotiga (/reports/stock) "Band" va "Erkin" ustunlarini qo'shish — operator band qilingan (waiting_production) va erkin miqdorni ko'rsin.

**Architecture:** Yangi batch helper `get_all_reservations(db)` bitta query bilan barcha band miqdorlarni qaytaradi. report_stock route joriy ko'rinishda har qatorga reserved/free qo'shadi. Template `show_reserved` bo'lsa 2 ustun ko'rsatadi. Faqat joriy ko'rinishda (band = hozirgi tushuncha).

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-06-06-stock-reservation-phase2c-ui-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `app/services/stock_reservation.py` (MODIFY) | `get_all_reservations` batch helper |
| `tests/test_reservation_ui.py` (YANGI) | helper unit test |
| `app/routes/reports.py` (MODIFY) | report_stock: reserved/free boyitish + show_reserved |
| `app/templates/reports/stock.html` (MODIFY) | Band/Erkin ustunlari + highlight + stat |

---

## Task 1: `get_all_reservations` batch helper (TDD)

**Files:**
- Modify: `app/services/stock_reservation.py`
- Test: `tests/test_reservation_ui.py` (yangi)

- [ ] **Step 1: Failing test**

`tests/test_reservation_ui.py`:
```python
"""Faza 2-C: reservation UI helper testlari."""
from datetime import datetime


def _waiting_order(db, wh_id, pid, qty, date, number):
    from app.models.database import Order, OrderItem
    o = Order(number=number, date=date, type="sale", source="agent",
              status="waiting_production", warehouse_id=wh_id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty))
    db.flush()
    return o


def test_get_all_reservations_empty(db):
    from app.services.stock_reservation import get_all_reservations
    assert get_all_reservations(db) == {}


def test_get_all_reservations_sums_by_wh_pid(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_all_reservations
    _waiting_order(db, sample_warehouse.id, sample_product.id, 25, datetime(2026, 6, 4), "W1")
    _waiting_order(db, sample_warehouse.id, sample_product.id, 5, datetime(2026, 6, 5), "W2")
    db.commit()
    m = get_all_reservations(db)
    assert m.get((sample_warehouse.id, sample_product.id)) == 30.0


def test_get_all_reservations_ignores_non_waiting(db, sample_warehouse, sample_product):
    from app.models.database import Order, OrderItem
    from app.services.stock_reservation import get_all_reservations
    o = Order(number="C1", date=datetime(2026, 6, 4), type="sale", source="agent",
              status="confirmed", warehouse_id=sample_warehouse.id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=sample_product.id, quantity=10))
    db.commit()
    assert get_all_reservations(db) == {}
```

- [ ] **Step 2: Run, FAIL**

`python -m pytest tests/test_reservation_ui.py -v` → ImportError (get_all_reservations yo'q).

- [ ] **Step 3: Helper qo'shish** — `app/services/stock_reservation.py` oxiriga:
```python
def get_all_reservations(db) -> dict:
    """Barcha waiting_production band miqdorlari: {(warehouse_id, product_id): qty}.
    Bitta guruhlangan query (per-qator alohida query o'rniga)."""
    wh_expr = func.coalesce(OrderItem.warehouse_id, Order.warehouse_id)
    rows = (
        db.query(
            wh_expr.label("wh"),
            OrderItem.product_id.label("pid"),
            func.coalesce(func.sum(OrderItem.quantity), 0.0).label("qty"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == "waiting_production", Order.type == "sale")
        .group_by(wh_expr, OrderItem.product_id)
        .all()
    )
    return {(r.wh, r.pid): float(r.qty or 0) for r in rows}
```

- [ ] **Step 4: Run, PASS**

`python -m pytest tests/test_reservation_ui.py -v` → 3 passed.

- [ ] **Step 5: Commit**
```bash
git add app/services/stock_reservation.py tests/test_reservation_ui.py
git commit -m "feat(stock): get_all_reservations batch helper (Faza 2-C)"
```

---

## Task 2: report_stock route — reserved/free boyitish

**Files:**
- Modify: `app/routes/reports.py` (`report_stock`, ~line 244 va template context ~265)

- [ ] **Step 1: Qator boyitish** — `report_stock` ichida, FIND:
```python
    stocks = [{"warehouse": v["warehouse"], "product": v["product"], "quantity": v["quantity"]} for v in values]
    if low:
```
REPLACE WITH:
```python
    stocks = [{"warehouse": v["warehouse"], "product": v["product"], "quantity": v["quantity"]} for v in values]
    # Band/Erkin — faqat joriy ko'rinishda (band = hozirgi tushuncha, tarixiy sanaga emas)
    show_reserved = not (report_date and str(report_date).strip())
    if show_reserved:
        from app.services.stock_reservation import get_all_reservations
        reserved_map = get_all_reservations(db)
        for s in stocks:
            wh = s.get("warehouse"); pr = s.get("product")
            rq = reserved_map.get((wh.id if wh else None, pr.id if pr else None), 0.0)
            s["reserved"] = rq
            s["free"] = float(s.get("quantity") or 0) - rq
    if low:
```

- [ ] **Step 2: Template context'ga `show_reserved`** — FIND:
```python
        "report_date": (report_date or "").strip()[:10] or None,
        "today": today_str,
```
REPLACE WITH:
```python
        "report_date": (report_date or "").strip()[:10] or None,
        "today": today_str,
        "show_reserved": show_reserved,
```

- [ ] **Step 3: Sintaksis + regressiya**

`python -m py_compile app/routes/reports.py && python -m pytest tests/ -q`
Expected: faqat oldindan ma'lum `test_login_get_returns_200` fail.

- [ ] **Step 4: Commit**
```bash
git add app/routes/reports.py
git commit -m "feat(stock): Qoldiq hisobotiga reserved/free boyitish (Faza 2-C)"
```

---

## Task 3: stock.html — Band/Erkin ustunlari + highlight + stat

**Files:**
- Modify: `app/templates/reports/stock.html`

- [ ] **Step 1: CSS qo'shish** — FIND:
```css
.stock-table tbody tr.low-stock td { background: #fff8f0; }
```
REPLACE WITH:
```css
.stock-table tbody tr.low-stock td { background: #fff8f0; }
.stock-table tbody tr.has-reserved td { background: #fffbea; }
.stock-table tbody tr.has-reserved.low-stock td { background: #fff3e0; }
```

- [ ] **Step 2: Band stat card** — FIND:
```html
{% set total_sum = namespace(v=0) %}
{% for s in stocks %}{% set total_sum.v = total_sum.v + (s.quantity * (s.product.purchase_price or 0)) %}{% endfor %}
```
REPLACE WITH:
```html
{% set total_sum = namespace(v=0) %}
{% for s in stocks %}{% set total_sum.v = total_sum.v + (s.quantity * (s.product.purchase_price or 0)) %}{% endfor %}
{% set band_ns = namespace(c=0) %}
{% if show_reserved %}{% for s in stocks %}{% if (s.reserved or 0) > 0.0001 %}{% set band_ns.c = band_ns.c + 1 %}{% endif %}{% endfor %}{% endif %}
```

- [ ] **Step 3: Band stat kartani qo'shish** — FIND:
```html
  <div class="col-6 col-md-3">
    <div class="stock-stat">
      <div class="num text-info">{{ warehouses|length }}</div>
      <div class="lbl">Omborlar</div>
    </div>
  </div>
</div>
{% endif %}
```
REPLACE WITH:
```html
  <div class="col-6 col-md-3">
    <div class="stock-stat">
      <div class="num text-info">{{ warehouses|length }}</div>
      <div class="lbl">Omborlar</div>
    </div>
  </div>
  {% if show_reserved and band_ns.c > 0 %}
  <div class="col-6 col-md-3">
    <div class="stock-stat" style="border-left:3px solid #f59e0b;">
      <div class="num text-warning">{{ band_ns.c }}</div>
      <div class="lbl">Band (waiting buyurtmalar)</div>
    </div>
  </div>
  {% endif %}
</div>
{% endif %}
```

- [ ] **Step 4: Jadval sarlavhasiga ustunlar** — FIND:
```html
          <th class="text-end">Qoldiq</th>
          <th class="text-end">Min</th>
```
REPLACE WITH:
```html
          <th class="text-end">Qoldiq</th>
          {% if show_reserved %}
          <th class="text-end">Band</th>
          <th class="text-end">Erkin</th>
          {% endif %}
          <th class="text-end">Min</th>
```

- [ ] **Step 5: Qator highlight class** — FIND:
```html
          <tr class="{% if _low %}low-stock{% endif %}">
```
REPLACE WITH:
```html
          <tr class="{% if _low %}low-stock{% endif %}{% if show_reserved and (stock.reserved or 0) > 0.0001 %} has-reserved{% endif %}">
```

- [ ] **Step 6: Qatorga Band/Erkin kataklar** — FIND:
```html
            <td class="text-end">
              <span class="qty-cell {% if (stock.quantity or 0) < 0 %}negative{% endif %}">
                {{ "{:,.0f}".format((stock.quantity or 0)|round(0)|int) if _is_dona else "{:,.3f}".format(stock.quantity or 0) }}
              </span>
            </td>
            <td class="text-end text-muted small">
```
REPLACE WITH:
```html
            <td class="text-end">
              <span class="qty-cell {% if (stock.quantity or 0) < 0 %}negative{% endif %}">
                {{ "{:,.0f}".format((stock.quantity or 0)|round(0)|int) if _is_dona else "{:,.3f}".format(stock.quantity or 0) }}
              </span>
            </td>
            {% if show_reserved %}
            <td class="text-end">
              {% set _r = stock.reserved or 0 %}
              {% if _r > 0.0001 %}<span class="fw-semibold text-warning">{{ "{:,.0f}".format(_r|round(0)|int) if _is_dona else "{:,.3f}".format(_r) }}</span>{% else %}<span class="text-muted">—</span>{% endif %}
            </td>
            <td class="text-end">
              {% set _f = stock.free or 0 %}
              <span class="fw-semibold {% if _f < 0 %}text-danger{% else %}text-success{% endif %}">{{ "{:,.0f}".format(_f|round(0)|int) if _is_dona else "{:,.3f}".format(_f) }}</span>
            </td>
            {% endif %}
            <td class="text-end text-muted small">
```

- [ ] **Step 7: Bo'sh holat colspan** — FIND:
```html
            <td colspan="10" class="text-center text-muted py-5">
```
REPLACE WITH:
```html
            <td colspan="{{ 12 if show_reserved else 10 }}" class="text-center text-muted py-5">
```

- [ ] **Step 8: Sintaksis (Jinja import) + commit**

Run: `python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('reports/stock.html'); print('template OK')"`
Expected: `template OK` (Jinja sintaksis xatosi yo'q).
```bash
git add app/templates/reports/stock.html
git commit -m "feat(stock): Qoldiq hisobotida Band/Erkin ustunlari (Faza 2-C)"
```

---

## Task 4: Yakuniy tekshirish

- [ ] **Step 1: To'liq suite**

`python -m pytest tests/ -q` → faqat oldindan ma'lum login fail.

- [ ] **Step 2: Deploy eslatmasi**

Tier A/C (faqat ko'rsatish, xulq o'zgarmaydi). Deploy [[project-deploy-runbook-20260507]]: backup → main merge → restart ([[reference-remote-restart-from-elyor]]) → /reports/stock ochib Band/Erkin ustunlari ko'rinishini tasdiqlash. Faza 2-B (admin override) qoldi.

---

## Self-Review

**Spec coverage:**
- §4.1 get_all_reservations → Task 1 ✓
- §4.2 route reserved/free + show_reserved → Task 2 ✓
- §4.3 template ustunlar + highlight + stat + sana-filtri yashirish → Task 3 (show_reserved gate) ✓
- §5 edge: band yo'q (—), manfiy erkin (qizil), sana-filtri (show_reserved=False) → Task 3 ✓
- §6 test → Task 1 ✓

**Placeholder scan:** Yo'q — har step to'liq kod.

**Type consistency:** `get_all_reservations(db)` → dict{(wh_id,pid):float}; route `s["reserved"]`/`s["free"]`; template `stock.reserved`/`stock.free`/`show_reserved` — izchil. JS filterStock cells[1]/[2] (nom/ombor) o'zgarmaydi (Band/Erkin Qoldiq'dan keyin, indeks 4-5). ✓
