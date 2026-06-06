# Stock Reservation Faza 2-B (Admin/Manager Override) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin/manager band tufayli bloklangan transfer va POS sotuvni `force` bilan "baribir o'tkaz" qila olsin (audit log bilan).

**Architecture:** Yangi `reservation_override(user, force)` helper + `log_reservation_override(...)` audit helper. Har band darvozasi `force` param qabul qiladi; override bo'lsa `reserved=0` (band chetlab o'tiladi), audit yoziladi. Transfer sahifasida admin/manager uchun "Baribir o'tkaz" tugmasi. POS JSON javobiga `reserved_block` flag (POS JS tugmasi alohida follow-up).

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-06-06-stock-reservation-phase2b-override-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `app/services/stock_reservation.py` (MODIFY) | `reservation_override` + `log_reservation_override` |
| `tests/test_reservation_override.py` (YANGI) | helper testlari |
| `app/routes/warehouse.py` (MODIFY) | transfer confirm + movement: force + override + audit |
| `app/routes/sales.py` (MODIFY) | sales_confirm + /pos/complete + employee-product: force + override + audit |
| `app/templates/warehouse/transfer_form.html` (MODIFY) | "Baribir o'tkaz" tugmasi |

---

## Task 1: override + audit helperlar (TDD)

**Files:**
- Modify: `app/services/stock_reservation.py`
- Test: `tests/test_reservation_override.py` (yangi)

- [ ] **Step 1: Failing test**

`tests/test_reservation_override.py`:
```python
"""Faza 2-B: admin/manager override helper testlari."""


class _U:
    def __init__(self, role, username="u"):
        self.role = role
        self.username = username


def test_override_admin_with_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("admin"), 1) is True


def test_override_manager_with_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("manager"), 1) is True


def test_override_seller_denied():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("sotuvchi"), 1) is False


def test_override_no_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("admin"), 0) is False


def test_override_none_user():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(None, 1) is False
```

- [ ] **Step 2: Run, FAIL** — `python -m pytest tests/test_reservation_override.py -v` → ImportError.

- [ ] **Step 3: Helperlar** — `app/services/stock_reservation.py` oxiriga:
```python
def reservation_override(current_user, force) -> bool:
    """force truthy VA role admin/manager bo'lsa True (band e'tiborga olinmaydi)."""
    if not force:
        return False
    role = getattr(current_user, "role", None) if current_user else None
    return role in ("admin", "manager", "menejer")


def log_reservation_override(db, current_user, entity_type, entity_number, reserved) -> None:
    """Band ustidan o'tilganda audit log (faqat haqiqiy band chetlab o'tilganda chaqirilsin)."""
    from app.models.database import AuditLog
    db.add(AuditLog(
        user_name=getattr(current_user, "username", None) or "system",
        action="reservation_override",
        entity_type=entity_type,
        entity_number=entity_number,
        details=f"reserved={float(reserved or 0):g} bypassed",
    ))
```

- [ ] **Step 4: Run, PASS** — `python -m pytest tests/test_reservation_override.py -v` → 5 passed.

- [ ] **Step 5: Commit**
```bash
git add app/services/stock_reservation.py tests/test_reservation_override.py
git commit -m "feat(stock): reservation_override + audit helper (Faza 2-B)"
```

---

## Task 2: warehouse.py — transfer confirm + movement override

**Files:**
- Modify: `app/routes/warehouse.py` (confirm ~622-664, movement ~810-835)

- [ ] **Step 1: transfer confirm imzosiga force** — FIND:
```python
@router.post("/transfers/{transfer_id}/confirm")
async def warehouse_transfer_confirm(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
```
REPLACE WITH:
```python
@router.post("/transfers/{transfer_id}/confirm")
async def warehouse_transfer_confirm(
    transfer_id: int,
    force: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
```

- [ ] **Step 2: transfer confirm stok tekshiruvi** — FIND (Faza 2-A kodi):
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
REPLACE WITH:
```python
    from app.utils.stock_at_date import get_stock_at_date
    from app.services.stock_reservation import get_reserved_quantity, reservation_override, log_reservation_override
    _override = reservation_override(current_user, force)
    for item in items:
        need = float(item.quantity or 0)
        physical = get_stock_at_date(db, transfer.from_warehouse_id, item.product_id, cutoff=_cutoff)
        reserved = 0.0 if _override else get_reserved_quantity(db, transfer.from_warehouse_id, item.product_id)
        have = physical - reserved
        if have + 1e-6 < need:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            name = prod.name if prod else f"#{item.product_id}"
            real_reserved = get_reserved_quantity(db, transfer.from_warehouse_id, item.product_id)
            avail_display = "0" if abs(have) < 1e-6 else ("%.6f" % have).rstrip("0").rstrip(".")
            date_hint = f" ({transfer.date.strftime('%d.%m.%Y')} sanasida)" if _cutoff else ""
            res_hint = f", {real_reserved:g} band (waiting buyurtmalar)" if real_reserved > 1e-6 else ""
            rb = "&reserved_block=1" if real_reserved > 1e-6 else ""
            return RedirectResponse(
                url=f"/warehouse/transfers/{transfer_id}?error=" + quote(f"Qayerdan omborda «{name}» yetarli emas (kerak: {item.quantity}, mavjud: {avail_display}{res_hint}{date_hint})") + rb,
                status_code=303,
            )
        if _override:
            real_reserved = get_reserved_quantity(db, transfer.from_warehouse_id, item.product_id)
            if real_reserved > 1e-6:
                log_reservation_override(db, current_user, "WarehouseTransfer", transfer.number, real_reserved)
```
(Eslatma: agar `get_stock_at_date` allaqachon faylda import qilingan bo'lsa, funksiya ichidagi takror import zararsiz — Python ruxsat beradi.)

- [ ] **Step 3: movement imzosiga force** — FIND:
```python
@router.post("/transfer")
async def warehouse_transfer(
    request: Request,
    from_warehouse_id: int = Form(...),
    to_warehouse_id: int = Form(...),
    product_id: int = Form(...),
    quantity: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
```
REPLACE WITH:
```python
@router.post("/transfer")
async def warehouse_transfer(
    request: Request,
    from_warehouse_id: int = Form(...),
    to_warehouse_id: int = Form(...),
    product_id: int = Form(...),
    quantity: float = Form(...),
    force: int = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
```

- [ ] **Step 4: movement stok tekshiruvi** — FIND (Faza 2-A kodi):
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
REPLACE WITH:
```python
    from app.services.stock_reservation import get_reserved_quantity, reservation_override, log_reservation_override
    source = db.query(Stock).filter(
        Stock.warehouse_id == from_warehouse_id,
        Stock.product_id == product_id,
    ).first()
    need_q = float(quantity or 0)
    real_reserved_q = get_reserved_quantity(db, from_warehouse_id, product_id)
    _override = reservation_override(current_user, force)
    reserved_q = 0.0 if _override else real_reserved_q
    have_q = (float(source.quantity or 0) if source else 0) - reserved_q
    if not source or (have_q + 1e-6 < need_q):
        product = db.query(Product).filter(Product.id == product_id).first()
        name = product.name if product else f"#{product_id}"
        avail_display = "0" if abs(have_q) < 1e-6 else ("%.6f" % have_q).rstrip("0").rstrip(".")
        res_hint = f", {real_reserved_q:g} band (waiting buyurtmalar)" if real_reserved_q > 1e-6 else ""
        return RedirectResponse(
            url="/warehouse/movement?error=1&detail=" + quote(f"Qayerdan omborda «{name}» yetarli emas (kerak: {quantity}, mavjud: {avail_display}{res_hint})"),
            status_code=303,
        )
    if _override and real_reserved_q > 1e-6:
        log_reservation_override(db, current_user, "WarehouseTransfer", f"movement {from_warehouse_id}->{to_warehouse_id}", real_reserved_q)
```

- [ ] **Step 5: Sintaksis + regressiya + commit**
```bash
python -m py_compile app/routes/warehouse.py && python -m pytest tests/ -q
git add app/routes/warehouse.py
git commit -m "feat(stock): transfer/movement admin override (Faza 2-B)"
```
Expected: faqat oldindan ma'lum login fail.

---

## Task 3: sales.py — POS gates override

**Files:**
- Modify: `app/routes/sales.py` (sales_confirm POS ~939-960, /pos/complete ~3760-3775)

- [ ] **Step 1: sales_confirm imzosiga force** — FIND:
```python
async def sales_confirm(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
```
REPLACE WITH:
```python
async def sales_confirm(
    order_id: int,
    force: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
```

- [ ] **Step 2: sales_confirm POS stok tekshiruvi** — FIND (Faza 1 kodi):
```python
    insufficient = []
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        have = get_available_stock(db, wh_id, item.product_id)
        need = float(item.quantity or 0)
        if have + 1e-6 < need:
```
REPLACE WITH:
```python
    from app.services.stock_reservation import get_reserved_quantity, reservation_override, log_reservation_override
    from app.utils.stock_at_date import get_stock_at_date
    _override = reservation_override(current_user, force)
    insufficient = []
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        if _override:
            have = get_stock_at_date(db, wh_id, item.product_id)  # jismoniy, band chetlab
            _rr = get_reserved_quantity(db, wh_id, item.product_id)
            if _rr > 1e-6:
                log_reservation_override(db, current_user, "Sale", order.number, _rr)
        else:
            have = get_available_stock(db, wh_id, item.product_id)
        need = float(item.quantity or 0)
        if have + 1e-6 < need:
```

- [ ] **Step 3: /pos/complete force (form'dan) + stok tekshiruvi** — FIND (Faza 2-A kodi):
```python
        stock = db.query(Stock).filter(
            Stock.warehouse_id == order.warehouse_id,
            Stock.product_id == pid
        ).with_for_update().first()
        # Band (waiting_production reservation) ayriladi — agentga va'da qilingan
        # mahsulotni POS sotmasligi uchun. Row lock saqlanadi (konkurensiya).
        avail = (float(stock.quantity or 0) if stock else 0.0) - get_reserved_quantity(db, order.warehouse_id, pid)
        if avail + 1e-6 < qty:
```
REPLACE WITH:
```python
        stock = db.query(Stock).filter(
            Stock.warehouse_id == order.warehouse_id,
            Stock.product_id == pid
        ).with_for_update().first()
        # Band ayriladi — lekin admin/manager force bilan o'tkaza oladi (Faza 2-B).
        from app.services.stock_reservation import reservation_override as _ovr, log_reservation_override as _logovr
        _pos_force = (form.get("force") or "").strip() in ("1", "true", "True")
        _pos_override = _ovr(current_user, 1 if _pos_force else 0)
        _real_res = get_reserved_quantity(db, order.warehouse_id, pid)
        avail = (float(stock.quantity or 0) if stock else 0.0) - (0.0 if _pos_override else _real_res)
        if _pos_override and _real_res > 1e-6:
            _logovr(db, current_user, "Sale", order.number, _real_res)
        if avail + 1e-6 < qty:
```
(`form` /pos/complete boshida `form = await request.form()` bilan mavjud.)

- [ ] **Step 4: Sintaksis + regressiya + commit**
```bash
python -m py_compile app/routes/sales.py && python -m pytest tests/ -q
git add app/routes/sales.py
git commit -m "feat(stock): POS confirm + /pos/complete admin override (Faza 2-B)"
```
Expected: faqat oldindan ma'lum login fail.

---

## Task 4: transfer_form.html — "Baribir o'tkaz" tugmasi

**Files:**
- Modify: `app/templates/warehouse/transfer_form.html` (error blok ~76-82)

- [ ] **Step 1: Error blokiga override tugmasi** — FIND:
```html
    {% if request.query_params.get('error') %}
```
Bu blok ichida (error matni ko'rsatilgandan keyin, blok yopilishidan oldin) QO'SHISH — error ko'rsatuvchi `<div>` ichiga, mavjud "Nima qilish" izohidan keyin:
```html
        {% if request.query_params.get('reserved_block') and current_user and current_user.role in ['admin', 'manager', 'menejer'] and transfer and transfer.status != 'confirmed' %}
        <div class="mt-2">
          <form method="post" action="/warehouse/transfers/{{ transfer.id }}/confirm?force=1" class="d-inline"
                onsubmit="return confirm('DIQQAT: bu mahsulot waiting buyurtmalarga band qilingan. Baribir o\'tkazasizmi? (audit logga yoziladi)');">
            <button type="submit" class="btn btn-warning btn-sm"><i class="bi bi-exclamation-triangle"></i> Baribir o'tkaz (admin/manager)</button>
          </form>
        </div>
        {% endif %}
```
(Aniq joy: `{% if request.query_params.get('error') %}` blokining ichida, error matn va izoh `<div>` ichida, `{% endif %}` dan oldin. Implementer error blokining to'liq tuzilishini o'qib, izohdan keyin joylashtirsin.)

- [ ] **Step 2: Jinja sintaksis + commit**
```bash
python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('warehouse/transfer_form.html'); print('OK')"
git add app/templates/warehouse/transfer_form.html
git commit -m "feat(stock): transfer sahifasida 'Baribir o'tkaz' tugmasi (Faza 2-B)"
```

---

## Task 5: regressiya + yakun

- [ ] **Step 1: To'liq suite**

`python -m pytest tests/ -q` → faqat oldindan ma'lum login fail.

- [ ] **Step 2: Deploy eslatmasi**

Tier B. Deploy: backup → main merge → restart ([[reference-remote-restart-from-elyor]], **deterministik: PID server.log 1-qatordan, kill, yangi PID + ~18s startup tasdiqla**) → /warehouse transferda band mahsulotni override tugmasi bilan sinash.

**Qolgan follow-up (bu plandan tashqarida):** POS pos.html JS'da band xato (`reserved_block`) ko'rsatilganda admin/manager uchun "Baribir sotish" tugmasi (`force=1` bilan qayta yuborish). Backend allaqachon tayyor (force qabul qiladi). employee-product + konversiya override ham keyin.

---

## Self-Review

**Spec coverage:**
- §3.1 reservation_override → Task 1 ✓; §3.2 audit (log_reservation_override) → Task 1 + har gate'da chaqiriladi ✓
- §4 darvozalar: transfer confirm (Task 2), movement (Task 2), sales_confirm (Task 3), /pos/complete (Task 3) ✓; quick-sale/employee-product → follow-up (Task 5 notes) — qisman, lekin asosiy POS yo'llar qamralди
- §5 UX: transfer tugma (Task 4) ✓; POS reserved_block flag (transfer'da qo'shildi; POS JSON flag + JS → follow-up)
- §6 edge: force+non-admin→band saqlanadi (Task 1 test); override+band yo'q→log yo'q (har gate `>1e-6` shart); override+jismoniy yetmasa→bloklanadi (have=physical-0, baribir tekshiriladi) ✓
- §7 test → Task 1 ✓

**Placeholder scan:** Task 2 Step 2 dagi `_gsad_noop` misol qatori — implementer olib tashlashi kerak (izohда aytilgan); Task 4 da error blok ichidagi aniq joy implementer'ga qoldirilgan (izoh bilan). Bular minimal — qolgan barcha kod to'liq.

**Type consistency:** `reservation_override(current_user, force)`, `log_reservation_override(db, current_user, entity_type, entity_number, reserved)`, `get_reserved_quantity(db, wh, pid)`, `get_stock_at_date(db, wh, pid, cutoff)` — barcha tasklarda izchil. ✓
