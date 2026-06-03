# Exchange Tahrirlash — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin yetkazilmagan agent almashtirishni (exchange) web'da tahrirlay olsin — qaytarish + yangi sotuv itemlarini o'zgartirish + partner balans qayta hisoblash.

**Architecture:** `sales.py` ga GET edit sahifa + POST update endpoint. Core logika `_apply_exchange_edit` helper'da (item almashtirish + total + recompute) — unit-testable. Exchange detail'da "Tahrirlash" tugmasi (yetkazilmagan uchun). Stock tegilmaydi (yetkazishdan oldin).

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2.0, Jinja2, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-06-02-exchange-edit-design.md`

---

## Muhim faktlar (verified)
- Exchange: `parent` (return_sale, parent_order_id=NULL) + `child` (sale, parent_order_id=parent.id). `sales_exchange_detail` (sales.py:467) ikkalasini template'ga uzatadi (`parent`, `child`).
- `Order`: type, status, partner_id, warehouse_id, subtotal, total, paid, debt, parent_order_id. `OrderItem`: order_id, product_id, quantity, price, discount_percent, total.
- `compute_partner_balance` **Order.total** ishlatadi (sale +total, return_sale −total). → total to'g'ri bo'lsa balans to'g'ri.
- Editable guard: status IN ('draft','confirmed') (delivered/completed/out_for_delivery emas) — ishonchli, stock-movement query shart emas.
- `recompute_partner_balance(db, pid, *, reason, ref=None, actor=None)` (DEPLOYED).
- `templates.TemplateResponse`, `require_admin`, `quote` — sales.py'da bor.
- conftest: `db`, `sample_partner`, `sample_product`.

## Fayl tuzilishi
| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/routes/sales.py` | `_apply_exchange_edit`, `_exchange_editable`, GET edit, POST update | Modify |
| `app/templates/sales/exchange_edit.html` | tahrir forma (2 jadval + JS) | YANGI |
| `app/templates/sales/exchange_detail.html` | "Tahrirlash" tugma | Modify |
| `tests/test_exchange_edit.py` | unit/integ | YANGI |

---

## Task 1: Core helperlar — `_exchange_editable` + `_apply_exchange_edit`

**Files:**
- Modify: `app/routes/sales.py`
- Test: `tests/test_exchange_edit.py` (YANGI)

- [ ] **Step 1: Failing test yoz**

`tests/test_exchange_edit.py`:
```python
from datetime import datetime
from app.models.database import Order, OrderItem, Partner, Product, Unit, PartnerBalanceDoc, PartnerBalanceDocItem
from app.routes.sales import _exchange_editable, _apply_exchange_edit


def _exchange(db, *, ret_lines, new_lines, status="confirmed"):
    u = Unit(name="kg"); db.add(u); db.flush()
    p = Partner(name="Mijoz", phone="+1", balance=0, is_active=True); db.add(p); db.flush()
    def _mkprod(pid):
        pr = db.query(Product).filter(Product.id == pid).first()
        if not pr:
            pr = Product(id=pid, name=f"P{pid}", unit_id=u.id, is_active=True); db.add(pr); db.flush()
        return pr
    parent = Order(number="AGT-R", type="return_sale", status=status, partner_id=p.id,
                   subtotal=0, total=0, paid=0, debt=0, date=datetime(2026,6,1))
    db.add(parent); db.flush()
    child = Order(number="AGT-S", type="sale", status=status, partner_id=p.id, parent_order_id=parent.id,
                  subtotal=0, total=0, paid=0, debt=0, date=datetime(2026,6,1))
    db.add(child); db.flush()
    for o, lines in ((parent, ret_lines), (child, new_lines)):
        tot = 0.0
        for pid, qty, price in lines:
            _mkprod(pid)
            db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty, price=price, total=qty*price))
            tot += qty*price
        o.subtotal = tot; o.total = tot
    db.commit()
    return parent, child, p


def test_editable_confirmed_true(db):
    parent, child, _ = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)], status="confirmed")
    assert _exchange_editable(parent, child) is True


def test_editable_delivered_false(db):
    parent, child, _ = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)], status="delivered")
    assert _exchange_editable(parent, child) is False


def test_apply_edit_replaces_items_and_total(db):
    parent, child, p = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)])
    # yangi sotuvni mahsulot 2 ga o'zgartiramiz (malina o'rniga)
    _apply_exchange_edit(db, parent, child,
                         ret_lines=[(1,5,43000)], new_lines=[(2,5,43000)], actor="admin")
    db.commit()
    db.refresh(child)
    items = db.query(OrderItem).filter(OrderItem.order_id == child.id).all()
    assert len(items) == 1 and items[0].product_id == 2
    assert child.total == 215000.0


def test_apply_edit_unequal_affects_balance(db):
    parent, child, p = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)])
    # yangi sotuv qimmatroq: +100000 -> mijoz qarzdor bo'ladi
    _apply_exchange_edit(db, parent, child,
                         ret_lines=[(1,5,43000)], new_lines=[(1,5,43000),(2,1,100000)], actor="admin")
    db.commit()
    db.refresh(p)
    # balans = sale(315000) - return(215000) = +100000
    assert p.balance == 100000.0


def test_apply_edit_equal_balance_zero(db):
    parent, child, p = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)])
    _apply_exchange_edit(db, parent, child,
                         ret_lines=[(3,2,50000)], new_lines=[(3,2,50000)], actor="admin")
    db.commit()
    db.refresh(p)
    assert p.balance == 0.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `python -m pytest tests/test_exchange_edit.py -v`
Expected: FAIL — ImportError (_exchange_editable / _apply_exchange_edit)

- [ ] **Step 3: Implementatsiya** — `app/routes/sales.py` ga qo'sh (modul darajasida, boshqa helperlar yonida):
```python
def _exchange_editable(parent, child) -> bool:
    """Yetkazilmagan exchange (har ikkala order draft/confirmed) tahrirlanadi."""
    ok = ("draft", "confirmed")
    return ((parent.status or "") in ok) and (child is None or (child.status or "") in ok)


def _apply_exchange_edit(db, parent, child, *, ret_lines, new_lines, actor=None):
    """Exchange itemlarini almashtiradi (ret_lines parent return_sale, new_lines child sale),
    total qayta hisoblaydi, partner balansni recompute qiladi. commit qilmaydi.
    ret_lines/new_lines: [(product_id, qty, price), ...].
    """
    from app.models.database import OrderItem as _OI
    for order, lines in ((parent, ret_lines), (child, new_lines)):
        if order is None:
            continue
        db.query(_OI).filter(_OI.order_id == order.id).delete(synchronize_session=False)
        tot = 0.0
        for pid, qty, price in lines:
            pid = int(pid); qty = float(qty); price = float(price)
            if pid <= 0 or qty <= 0:
                continue
            line_total = qty * price
            db.add(_OI(order_id=order.id, product_id=pid, quantity=qty, price=price,
                       discount_percent=0, total=line_total))
            tot += line_total
        order.subtotal = tot
        order.total = tot
    db.flush()
    pid_set = {o.partner_id for o in (parent, child) if o is not None and o.partner_id}
    from app.services.partner_balance_service import recompute_partner_balance
    for pid in pid_set:
        recompute_partner_balance(db, pid, reason="exchange_edit",
                                  ref=parent.number if parent else None, actor=actor)
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `python -m pytest tests/test_exchange_edit.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**
```bash
git add app/routes/sales.py tests/test_exchange_edit.py
git commit -m "feat(exchange): _exchange_editable + _apply_exchange_edit core + testlar"
```

---

## Task 2: GET edit sahifa + POST update endpoint

**Files:**
- Modify: `app/routes/sales.py`

- [ ] **Step 1: GET edit endpoint** — `sales_exchange_detail` (sales.py:467) dan keyin qo'sh:
```python
@router.get("/exchange/{order_id}/edit", response_class=HTMLResponse)
async def sales_exchange_edit(request: Request, order_id: int,
                              db: Session = Depends(get_db),
                              current_user: User = Depends(require_admin)):
    parent = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.partner),
    ).filter(Order.id == order_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Obmen topilmadi")
    if parent.parent_order_id:
        return RedirectResponse(url=f"/sales/exchange/{parent.parent_order_id}/edit", status_code=303)
    child = db.query(Order).options(joinedload(Order.items).joinedload(OrderItem.product)).filter(
        Order.parent_order_id == parent.id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Obmen ning sale qismi topilmadi")
    if not _exchange_editable(parent, child):
        return RedirectResponse(url=f"/sales/exchange/{parent.id}?error=" + quote(
            "Faqat yetkazilmagan (qoralama/tasdiqlangan) almashtirishni tahrirlash mumkin."), status_code=303)
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
    return templates.TemplateResponse("sales/exchange_edit.html", {
        "request": request, "parent": parent, "child": child,
        "products": products, "current_user": current_user,
        "page_title": f"Tahrir: {parent.number} ↔ {child.number}",
    })
```

- [ ] **Step 2: POST update endpoint** — yoniga qo'sh:
```python
@router.post("/exchange/{order_id}/update")
async def sales_exchange_update(request: Request, order_id: int,
                                db: Session = Depends(get_db),
                                current_user: User = Depends(require_admin)):
    parent = db.query(Order).filter(Order.id == order_id).first()
    if not parent or parent.parent_order_id:
        raise HTTPException(status_code=404, detail="Obmen topilmadi")
    child = db.query(Order).filter(Order.parent_order_id == parent.id, Order.type == "sale").first()
    if not child:
        raise HTTPException(status_code=404, detail="Obmen ning sale qismi topilmadi")
    if not _exchange_editable(parent, child):
        return RedirectResponse(url=f"/sales/exchange/{parent.id}?error=" + quote(
            "Yetkazilgan almashtirishni tahrirlab bo'lmaydi."), status_code=303)
    form = await request.form()
    def _lines(prefix):
        pids = form.getlist(f"{prefix}_product_id")
        qtys = form.getlist(f"{prefix}_quantity")
        prices = form.getlist(f"{prefix}_price")
        out = []
        for i in range(min(len(pids), len(qtys), len(prices))):
            try:
                pid = int(pids[i]); qty = float(qtys[i]); price = float(prices[i])
            except (ValueError, TypeError):
                continue
            if pid > 0 and qty > 0:
                out.append((pid, qty, price))
        return out
    ret_lines = _lines("ret")
    new_lines = _lines("new")
    if not ret_lines or not new_lines:
        return RedirectResponse(url=f"/sales/exchange/{parent.id}/edit?error=" + quote(
            "Qaytarish va yangi sotuvda kamida bitta mahsulot bo'lishi kerak."), status_code=303)
    _apply_exchange_edit(db, parent, child, ret_lines=ret_lines, new_lines=new_lines,
                         actor=current_user.username if current_user else None)
    db.commit()
    return RedirectResponse(url=f"/sales/exchange/{parent.id}?edited=1", status_code=303)
```

- [ ] **Step 3: Sintaksis + testlar**

Run: `python -c "import ast; ast.parse(open(r'app/routes/sales.py', encoding='utf-8').read()); print('OK')"`
Run: `python -m pytest tests/ -q`
Expected: OK; baseline 4 fail'dan oshmaydi

- [ ] **Step 4: Commit**
```bash
git add app/routes/sales.py
git commit -m "feat(exchange): GET edit sahifa + POST update endpoint"
```

---

## Task 3: Tahrir forma template — `exchange_edit.html`

**Files:**
- Create: `app/templates/sales/exchange_edit.html`

- [ ] **Step 1: Template yoz** — `app/templates/sales/exchange_edit.html`. `base.html` extend qiladi, `POST /sales/exchange/{{ parent.id }}/update` formasi, 2 jadval (qaytarish/yangi), har qator: mahsulot select (products), miqdor, narx. JS: qator qo'shish/o'chirish + jonli jami. CSRF token (`csrf_token_from_request(request)`).
```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid">
  <div class="page-header">
    <h4><i class="bi bi-pencil"></i> Almashtirishni tahrirlash: {{ parent.number }} ↔ {{ child.number }}</h4>
    <a href="/sales/exchange/{{ parent.id }}" class="btn top-btn btn-outline-secondary"><i class="bi bi-arrow-left"></i> Orqaga</a>
  </div>
  <form method="post" action="/sales/exchange/{{ parent.id }}/update">
    <input type="hidden" name="csrf_token" value="{{ csrf_token_from_request(request) }}">
    {% for side, prefix, items, title, color in [('ret','ret', parent.items, 'Qaytarish (mijozdan)', 'warning'), ('new','new', child.items, 'Yangi sotuv (mijozga)', 'success')] %}
    <div class="card mb-3">
      <div class="card-header bg-{{ color }} text-white d-flex justify-content-between">
        <strong>{{ title }}</strong>
        <button type="button" class="btn btn-sm btn-light" onclick="addRow('{{ prefix }}')">+ Qator</button>
      </div>
      <table class="table mb-0" id="tbl-{{ prefix }}">
        <thead><tr><th>Mahsulot</th><th style="width:120px">Miqdor</th><th style="width:140px">Narx</th><th style="width:40px"></th></tr></thead>
        <tbody>
        {% for it in items %}
          <tr>
            <td><select name="{{ prefix }}_product_id" class="form-select form-select-sm">
              {% for p in products %}<option value="{{ p.id }}" {% if p.id==it.product_id %}selected{% endif %}>{{ p.name }}</option>{% endfor %}
            </select></td>
            <td><input type="number" name="{{ prefix }}_quantity" class="form-control form-control-sm" step="any" min="0" value="{{ it.quantity }}"></td>
            <td><input type="number" name="{{ prefix }}_price" class="form-control form-control-sm" step="any" min="0" value="{{ it.price|int }}"></td>
            <td><button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('tr').remove()">×</button></td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    {% endfor %}
    <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> Saqlash</button>
  </form>
</div>
<template id="rowtpl">
  <tr>
    <td><select name="__P___product_id" class="form-select form-select-sm">
      {% for p in products %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}
    </select></td>
    <td><input type="number" name="__P___quantity" class="form-control form-control-sm" step="any" min="0" value="1"></td>
    <td><input type="number" name="__P___price" class="form-control form-control-sm" step="any" min="0" value="0"></td>
    <td><button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('tr').remove()">×</button></td>
  </tr>
</template>
<script>
// XSS-xavfsiz: <template> node'ini klonlash (innerHTML EMAS), name atributini DOM orqali yangilash
function addRow(prefix){
  var tpl = document.getElementById('rowtpl');
  var clone = tpl.content.cloneNode(true);
  clone.querySelectorAll('[name]').forEach(function(el){ el.name = el.name.replace('__P__', prefix); });
  document.querySelector('#tbl-'+prefix+' tbody').appendChild(clone);
}
</script>
{% endblock %}
```

- [ ] **Step 2: Render tekshiruvi** — server'da `/sales/exchange/63/edit` ochib forma ko'rinishini ko'rish (manual; template auto-reload). Yoki AST/Jinja sintaksis: template Jinja syntax error bermasligi (server log toza).

- [ ] **Step 3: Commit**
```bash
git add app/templates/sales/exchange_edit.html
git commit -m "feat(exchange): tahrir forma template (2 jadval + qator qo'shish)"
```

---

## Task 4: "Tahrirlash" tugma — `exchange_detail.html`

**Files:**
- Modify: `app/templates/sales/exchange_detail.html`

- [ ] **Step 1: Tugma qo'sh** — mavjud tugmalar (Chop etish / Excel / Orqaga) yoniga, faqat yetkazilmagan uchun. `exchange_detail.html` da tugmalar blokini topib qo'sh:
```html
{% if parent.status in ['draft','confirmed'] and child.status in ['draft','confirmed'] and current_user.role in ['admin','manager'] %}
<a href="/sales/exchange/{{ parent.id }}/edit" class="btn top-btn btn-warning">
  <i class="bi bi-pencil"></i> Tahrirlash
</a>
{% endif %}
```

- [ ] **Step 2: Render tekshiruvi** — `/sales/exchange/63` da tugma ko'rinadi (olcha draft/confirmed). Manual.

- [ ] **Step 3: Commit**
```bash
git add app/templates/sales/exchange_detail.html
git commit -m "feat(exchange): exchange detail'ga Tahrirlash tugma"
```

---

## Task 5: To'liq test + smoke
- [ ] `python -m pytest tests/ -q` → faqat 4 baseline fail
- [ ] `python -m pytest tests/test_exchange_edit.py -v` → 5 passed
- [ ] AST: sales.py OK

---

## Task 6: Deploy (tungi/hozir, controller)
- [ ] Backup `totli_holva.db.bak_pre_exchange_edit_20260602`
- [ ] Server restart (DCOM kill 8080 + schtasks run)
- [ ] Post-smoke: `/sales/exchange/63/edit` ochiladi, malina o'rniga boshqa mahsulot tanlab saqlash → detail'da yangilangan ko'rinadi, balans to'g'ri
- [ ] Rollback: backup + git revert

---

## Self-Review natijasi
**Spec coverage:** editable guard + apply (T1), GET edit + POST update (T2), template forma (T3), Tahrirlash tugma (T4), test (T5), deploy (T6) — barcha spec bo'limlari qoplangan. ✅
**Placeholder scan:** to'liq kod + template; "edge case" mavhumligi yo'q. ✅
**Type consistency:** `_exchange_editable(parent, child)->bool`, `_apply_exchange_edit(db, parent, child, *, ret_lines, new_lines, actor=None)`, form prefiks `ret_`/`new_` — izchil. ✅
