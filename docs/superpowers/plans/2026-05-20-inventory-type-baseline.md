# Inventory `type` ustuni + ishonchli baseline — implementatsiya rejasi

> **Agentik ishchilar uchun:** SUB-SKILL: `superpowers:subagent-driven-development` (tavsiya) yoki `superpowers:executing-plans` ishlatiladi. Qadamlar checkbox (`- [ ]`) sintaksisida.

**Spec:** [docs/superpowers/specs/2026-05-20-inventory-set-add-type-and-baseline-fix-design.md](../specs/2026-05-20-inventory-set-add-type-and-baseline-fix-design.md) (commit `d5ace00`)

**Goal:** `/inventory/` confirm da SET/ADD ni `doc.type` ustuni orqali aniq qilish va `old_qty` ni `last_mv.quantity_after` o'rniga `get_stock_at_date_batch(cutoff=doc_date)` dan olish — back-dated sintetik InitialBalance qatorlari Stock'ni buzmasin.

**Architecture:** `StockAdjustmentDoc.type` ustuni (additive, default `'inventory'`); `inventory_create_draft` Form'dan tur oladi; `inventory_confirm` POST tur'ini hujjat turi bilan solishtiradi; `_apply_inventory_stock_changes` `last_mv` lookup'ni `get_stock_at_date_batch` bilan almashtiradi. Eski hujjatlar harakat note'idan backfill.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Jinja2, pytest, SQLite

**Branch:** `feat-inventory-type-baseline` (spec commit `d5ace00` — `feat-bulk-dispatch` da; yangi branch shundan ajraladi)

---

## Task 1: ORM modeliga `type` ustunini qo'shish (TDD)

**Files:**
- Modify: `app/models/database.py:447-466` (StockAdjustmentDoc klassi)
- Create: `tests/test_inventory_type.py`

- [ ] **Step 1.1: Yiqilgan test yozish — type ustuni mavjud va default 'inventory'**

`tests/test_inventory_type.py` yarating:
```python
"""StockAdjustmentDoc.type ustuni regressiya testlari."""
from datetime import datetime
from app.models.database import StockAdjustmentDoc


def test_type_column_defaults_to_inventory(db):
    doc = StockAdjustmentDoc(
        number="INV-TEST-1", date=datetime.now(),
        warehouse_id=1, user_id=1, status="draft",
    )
    db.add(doc); db.commit()
    db.refresh(doc)
    assert doc.type == "inventory", "default tur Inventarizatsiya bo'lishi kerak"


def test_type_column_accepts_stock_entry(db):
    doc = StockAdjustmentDoc(
        number="INV-TEST-2", date=datetime.now(),
        warehouse_id=1, user_id=1, status="draft", type="stock_entry",
    )
    db.add(doc); db.commit()
    db.refresh(doc)
    assert doc.type == "stock_entry"
```

- [ ] **Step 1.2: Testni ishga tushirib yiqilishini ko'rish**

Run: `python -m pytest tests/test_inventory_type.py -v`
Expected: FAIL with `AttributeError: 'StockAdjustmentDoc' object has no attribute 'type'` yoki shunga o'xshash.

- [ ] **Step 1.3: Modelga ustun qo'shish**

`app/models/database.py:447-466` ichida `created_at` qatoridan SO'NG (~459-qatorga), `warehouse = relationship(...)` qatoridan OLDIN qo'shing:
```python
    type = Column(String(20), default="inventory", nullable=True)  # 'inventory' (SET) | 'stock_entry' (ADD)
```

- [ ] **Step 1.4: Testni qayta ishga tushirib o'tishini ko'rish**

Run: `python -m pytest tests/test_inventory_type.py -v`
Expected: 2 passed.

- [ ] **Step 1.5: Commit**

```bash
git add app/models/database.py tests/test_inventory_type.py
git commit -m "feat(inventory): StockAdjustmentDoc.type ustuni (model + test)"
```

---

## Task 2: Jonli DB uchun migration helper

**Files:**
- Modify: `app/utils/db_schema.py` (oxiriga yangi funksiya)

- [ ] **Step 2.1: `ensure_stock_adjustment_doc_type_column` qo'shish**

`app/utils/db_schema.py` faylining oxiriga qo'shing:
```python
def ensure_stock_adjustment_doc_type_column(db: Session) -> None:
    """stock_adjustment_docs jadvalida type ustuni yo'q bo'lsa qo'shadi."""
    try:
        db.execute(text(
            "ALTER TABLE stock_adjustment_docs "
            "ADD COLUMN type VARCHAR(20) DEFAULT 'inventory'"
        ))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()
```

- [ ] **Step 2.2: Helperning idempotent ekanini tekshirish**

`tests/test_inventory_type.py` ga qo'shing:
```python
def test_ensure_helper_idempotent(db):
    from app.utils.db_schema import ensure_stock_adjustment_doc_type_column
    # In-memory DB'da model orqali ustun allaqachon bor; helper xato bermasligi kerak
    ensure_stock_adjustment_doc_type_column(db)
    ensure_stock_adjustment_doc_type_column(db)  # 2-marta — duplicate column ushlanishi kerak
```

Run: `python -m pytest tests/test_inventory_type.py::test_ensure_helper_idempotent -v`
Expected: PASS.

- [ ] **Step 2.3: Commit**

```bash
git add app/utils/db_schema.py tests/test_inventory_type.py
git commit -m "feat(inventory): ensure_stock_adjustment_doc_type_column migration helper"
```

---

## Task 3: D2 — yiqilgan regressiya testi (back-dated sintetik baseline)

**Files:**
- Create: `tests/test_inventory_confirm_baseline.py`

- [ ] **Step 3.1: Test fixture va yiqilgan test yozish**

`tests/test_inventory_confirm_baseline.py` yarating:
```python
"""_apply_inventory_stock_changes baseline tuzog'i regressiyasi (D2).

WH2 KAROBKA 2026-05-19 incidentini takrorlaydi: back-dated sintetik
InitialBalance qatori (eng katta ID, ancient created_at, quantity_after=axlat)
last_mv lookup'da topilib, old_qty ga axlat qaytarganda Stock buziladi.
"""
from datetime import datetime
import pytest
from sqlalchemy import text
from app.models.database import (
    StockAdjustmentDoc, StockAdjustmentDocItem,
    Stock, StockMovement, Product, Warehouse,
)
from app.routes.warehouse import _apply_inventory_stock_changes


def _setup_corrupt_baseline(db):
    """Buzuq Ledger: real stacked-INIT + sintetik DRIFT-FIX (yuqori ID, qadimiy sana)."""
    wh = Warehouse(id=99, name="Test WH", is_active=True); db.add(wh)
    prod = Product(id=999, code="P-T", name="Test KAROBKA", is_active=True); db.add(prod)
    stock = Stock(warehouse_id=99, product_id=999, quantity=-1200.0); db.add(stock)
    db.flush()
    sid = stock.id
    # Real stacked-INIT (kichik IDlar, ancient sanalar) — ledger SUM ni quradi
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="initial_balance",
        document_type="InitialBalance", document_id=0, document_number="INIT-BALANCE",
        quantity_change=2000.0, quantity_after=2000.0,
        created_at=datetime(2026, 3, 4, 14, 58, 42),
    ))
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="initial_balance",
        document_type="InitialBalance", document_id=0, document_number="INIT-BALANCE-RETRO",
        quantity_change=3000.0, quantity_after=3000.0,
        created_at=datetime(2026, 4, 13, 13, 4, 15),
    ))
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="adjustment",
        document_type="StockAdjustmentDoc", document_id=0, document_number="INV-PRIOR",
        quantity_change=-15.0, quantity_after=2970.0,
        created_at=datetime(2026, 5, 8, 18, 28, 0),
    ))
    # SINTETIK DRIFT-FIX: ancient sana LEKIN INSERT vaqti yangi (id eng katta bo'ladi)
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="initial_out",
        document_type="InitialBalance", document_id=0,
        document_number="INIT-DRIFT-FIX-W99-P999-20260513",
        quantity_change=-3000.0, quantity_after=-3000.0,  # AXLAT quantity_after
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    ))
    db.commit()
    return wh, prod, stock


def test_set_mode_ignores_corrupt_quantity_after(db):
    """Inventarizatsiya (SET): jismoniy=1800 -> Stock=1800, Ledger SUM=1800."""
    wh, prod, stock = _setup_corrupt_baseline(db)
    doc = StockAdjustmentDoc(
        number="INV-T-SET", date=datetime(2026, 5, 19, 14, 53),
        warehouse_id=99, user_id=None, status="draft", type="inventory",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(
        doc_id=doc.id, warehouse_id=99, product_id=999,
        quantity=1800.0, cost_price=0.0, sale_price=0.0,
    ))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=False, current_user=None)
    db.commit()
    stock_q = db.query(Stock).filter_by(warehouse_id=99, product_id=999).first().quantity
    led = db.execute(text(
        "SELECT COALESCE(SUM(quantity_change),0) FROM stock_movements "
        "WHERE warehouse_id=99 AND product_id=999"
    )).scalar()
    assert abs(float(stock_q) - 1800.0) < 1e-3, f"Stock {stock_q} != 1800 (SET)"
    assert abs(float(led) - 1800.0) < 1e-3, f"Ledger SUM {led} != 1800 (SET)"


def test_add_mode_uses_clean_baseline(db):
    """Tovar qoldiqlari (ADD): jismoniy=1800 ustiga qo'shiladi.
    Toza baseline = SUM≤doc_date = 2000+3000-15-3000 = 1985.
    Kutilgan: Stock = 1985 + 1800 = 3785 (axlat -3000 emas)."""
    wh, prod, stock = _setup_corrupt_baseline(db)
    doc = StockAdjustmentDoc(
        number="INV-T-ADD", date=datetime(2026, 5, 19, 14, 53),
        warehouse_id=99, user_id=None, status="draft", type="stock_entry",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(
        doc_id=doc.id, warehouse_id=99, product_id=999,
        quantity=1800.0, cost_price=0.0, sale_price=0.0,
    ))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=True, current_user=None)
    db.commit()
    stock_q = db.query(Stock).filter_by(warehouse_id=99, product_id=999).first().quantity
    led = db.execute(text(
        "SELECT COALESCE(SUM(quantity_change),0) FROM stock_movements "
        "WHERE warehouse_id=99 AND product_id=999"
    )).scalar()
    assert abs(float(stock_q) - 3785.0) < 1e-3, f"Stock {stock_q} != 3785 (ADD)"
    assert abs(float(led) - 3785.0) < 1e-3, f"Ledger SUM {led} != 3785 (ADD)"
```

- [ ] **Step 3.2: Testni ishga tushirib yiqilishini ko'rish (D2 mavjud)**

Run: `python -m pytest tests/test_inventory_confirm_baseline.py -v`
Expected:
- `test_set_mode_ignores_corrupt_quantity_after` — yiqiladi YOKI o'tadi (eski kodda SET final formula `new + after` — old_qty ishlatmaydi → Stock to'g'ri keladi; lekin LEDGER drift bo'lishi mumkin, assertion ledger uchun yiqiladi)
- `test_add_mode_uses_clean_baseline` — **yiqiladi** (eski kodda old_qty = quantity_after = −3000 → Stock = −1200, ledger ham 0)

Agar `test_set_mode_...` o'tib ketsa ham OK — D2 ning ADD ta'siri asosiy. Yiqilgan testlarni qo'lda bag mavjudligini tasdiqlash uchun chiqarishni saqlang.

- [ ] **Step 3.3: Commit (yiqilgan testlar — TDD)**

```bash
git add tests/test_inventory_confirm_baseline.py
git commit -m "test(inventory): D2 regressiya — back-dated sintetik baseline (yiqiladi)"
```

---

## Task 4: D2 fix — `get_stock_at_date_batch` baseline

**Files:**
- Modify: `app/routes/warehouse.py:1514-1620` (`_apply_inventory_stock_changes`)

- [ ] **Step 4.1: Funksiyani almashtirish**

`app/routes/warehouse.py` da `_apply_inventory_stock_changes` ni quyidagiga almashtiring (Batch 2 va Batch 3 dan biri va loop ichidagi `last_mv` o'qish olib tashlanadi; baseline `get_stock_at_date_batch` dan):

```python
def _apply_inventory_stock_changes(db: Session, doc, is_stock_entry: bool, current_user) -> int:
    """Inventarizatsiya/tovar qoldiqlari hujjati uchun stock movementlarni yaratadi
    va Stock.quantity ni hujjat sanasidan keyingi harakatlar bilan birga yangilaydi.
    Returns: ishlangan itemlar soni.

    BASELINE: get_stock_at_date_batch (SUM<=doc_date) - quantity_after ishonchsiz.
    """
    from sqlalchemy import func as sqla_func
    from app.utils.stock_at_date import get_stock_at_date_batch
    items_snapshot = [
        {
            "item": item,
            "warehouse_id": item.warehouse_id,
            "product_id": item.product_id,
            "quantity": float(item.quantity or 0),
        }
        for item in doc.items
    ]
    if not items_snapshot:
        return 0
    doc_date = doc.date or datetime.now()
    pairs = list({(s["warehouse_id"], s["product_id"]) for s in items_snapshot})
    whs = list({w for w, _ in pairs})
    pids = list({p for _, p in pairs})

    # Stock rowlar (final overwrite uchun)
    stock_rows_by_pair: dict = {}
    if whs and pids:
        for s in db.query(Stock).filter(Stock.warehouse_id.in_(whs), Stock.product_id.in_(pids)).all():
            stock_rows_by_pair.setdefault((s.warehouse_id, s.product_id), s)

    # BASELINE: warehouse bo'yicha guruhlab batch chaqirig'i (D2 fix)
    old_qty_by_pair: dict = {}
    pids_by_wh: dict = {}
    for w, p in pairs:
        pids_by_wh.setdefault(w, []).append(p)
    for w, ps in pids_by_wh.items():
        qmap = get_stock_at_date_batch(db, warehouse_id=w, product_ids=ps, cutoff=doc_date)
        for p, q in qmap.items():
            old_qty_by_pair[(w, p)] = float(q or 0)

    # doc_date dan keyingi non-adjustment SUM(quantity_change) - mavjud
    after_changes_by_pair: dict = {}
    if whs and pids:
        for r in (
            db.query(
                StockMovement.warehouse_id,
                StockMovement.product_id,
                sqla_func.coalesce(sqla_func.sum(StockMovement.quantity_change), 0).label("delta"),
            )
            .filter(
                StockMovement.warehouse_id.in_(whs),
                StockMovement.product_id.in_(pids),
                StockMovement.created_at > doc_date,
                StockMovement.operation_type != "adjustment",
            )
            .group_by(StockMovement.warehouse_id, StockMovement.product_id)
            .all()
        ):
            after_changes_by_pair[(r.warehouse_id, r.product_id)] = float(r.delta or 0)

    for snap in items_snapshot:
        key = (snap["warehouse_id"], snap["product_id"])
        old_qty = old_qty_by_pair.get(key, 0.0)
        new_qty = snap["quantity"]
        if hasattr(snap["item"], "previous_quantity"):
            snap["item"].previous_quantity = old_qty
        quantity_change = new_qty if is_stock_entry else (new_qty - old_qty)
        if abs(quantity_change) <= 1e-9:
            continue
        create_stock_movement(
            db=db,
            warehouse_id=snap["warehouse_id"],
            product_id=snap["product_id"],
            quantity_change=quantity_change,
            operation_type="adjustment",
            document_type="StockAdjustmentDoc",
            document_id=doc.id,
            document_number=doc.number,
            user_id=current_user.id if current_user else None,
            note=f"{'Tovar qoldiqlari' if is_stock_entry else 'Inventarizatsiya'}: {doc.number}",
            created_at=doc.date,
        )
        stock_row = stock_rows_by_pair.get(key)
        if stock_row:
            after_changes = after_changes_by_pair.get(key, 0.0)
            if is_stock_entry:
                stock_row.quantity = old_qty + new_qty + after_changes
            else:
                stock_row.quantity = new_qty + after_changes
    return len(items_snapshot)
```

(Diff: `last_mv_id_rows`, `last_mv_by_pair`, `stock_sum_fallback` olib tashlandi; ularning o'rniga `old_qty_by_pair` va `get_stock_at_date_batch` chaqirig'i.)

- [ ] **Step 4.2: Task 3 testlari endi o'tishi kerak**

Run: `python -m pytest tests/test_inventory_confirm_baseline.py -v`
Expected: 2 passed.

- [ ] **Step 4.3: Mavjud regressiya yo'q bo'lishi**

Run: `python -m pytest tests/ -v -x --ignore=tests/test_endpoints_smoke.py`
Expected: barcha mavjud testlar o'tishi (yoki avval ham yiqilganlar — `git stash` qiling va yiqilgan testlar yangi bagmi yoki eski stale ekanini tekshiring; eski stale bo'lsa o'zgartirmang).

- [ ] **Step 4.4: Commit**

```bash
git add app/routes/warehouse.py
git commit -m "fix(inventory): D2 — _apply_inventory_stock_changes baseline get_stock_at_date_batch'dan

Eski: old_qty = last_mv.quantity_after (MAX id <= doc_date) — back-dated
sintetik InitialBalance qatorlaridan axlat qaytarardi. Yangi: warehouse
bo'yicha guruhlangan get_stock_at_date_batch(cutoff=doc_date) — toza
SUM(quantity_change) <= doc_date."
```

---

## Task 5: D1 — yiqilgan test (`is_stock_entry` `doc.type` dan)

**Files:**
- Create: `tests/test_inventory_type_switch.py`

- [ ] **Step 5.1: TestClient orqali end-to-end test**

`tests/test_inventory_type_switch.py` yarating:
```python
"""D1 regressiya: is_stock_entry doc.type'dan o'qiladi (number prefiksidan emas)."""
from datetime import datetime
from app.models.database import (
    StockAdjustmentDoc, StockAdjustmentDocItem, Stock,
    Product, Warehouse,
)
from app.routes.warehouse import _apply_inventory_stock_changes


def test_type_inventory_does_set(db):
    """type='inventory' -> SET semantika."""
    db.add(Warehouse(id=98, name="T", is_active=True))
    db.add(Product(id=998, code="P-S", name="T", is_active=True))
    db.add(Stock(warehouse_id=98, product_id=998, quantity=100.0))
    doc = StockAdjustmentDoc(
        number="INV-PENDING-X", date=datetime.now(),
        warehouse_id=98, status="draft", type="inventory",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(doc_id=doc.id, warehouse_id=98, product_id=998, quantity=50.0))
    db.flush(); db.refresh(doc)
    # is_stock_entry False (SET) — type='inventory' bo'lsa kutilgan natija:
    _apply_inventory_stock_changes(db, doc, is_stock_entry=False, current_user=None)
    db.commit()
    s = db.query(Stock).filter_by(warehouse_id=98, product_id=998).first().quantity
    assert abs(float(s) - 50.0) < 1e-3, f"SET kutilgan 50, oldi {s}"


def test_type_stock_entry_does_add(db):
    """type='stock_entry' -> ADD semantika."""
    db.add(Warehouse(id=97, name="T", is_active=True))
    db.add(Product(id=997, code="P-A", name="T", is_active=True))
    db.add(Stock(warehouse_id=97, product_id=997, quantity=100.0))
    doc = StockAdjustmentDoc(
        number="INV-PENDING-Y", date=datetime.now(),
        warehouse_id=97, status="draft", type="stock_entry",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(doc_id=doc.id, warehouse_id=97, product_id=997, quantity=50.0))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=True, current_user=None)
    db.commit()
    s = db.query(Stock).filter_by(warehouse_id=97, product_id=997).first().quantity
    assert abs(float(s) - 150.0) < 1e-3, f"ADD kutilgan 150 (100+50), oldi {s}"
```

- [ ] **Step 5.2: Testlarni ishga tushirish (Task 4'dan keyin o'tishi kerak)**

Run: `python -m pytest tests/test_inventory_type_switch.py -v`
Expected: 2 passed (chunki `_apply_inventory_stock_changes` `is_stock_entry` ni parametr sifatida oladi — bu testlar D1 ning **mexanikasini** tasdiqlaydi; D1 ning **manbasi** (`inventory_confirm` da type'dan o'qish) Task 6'da).

- [ ] **Step 5.3: Commit**

```bash
git add tests/test_inventory_type_switch.py
git commit -m "test(inventory): D1 — is_stock_entry semantika testlari"
```

---

## Task 6: D1 fix — `inventory_confirm` `doc.type` dan o'qish

**Files:**
- Modify: `app/routes/warehouse.py:1407-1496` (`inventory_confirm`)

- [ ] **Step 6.1: `is_stock_entry` manbasini almashtirish + POST tasdig'i**

`app/routes/warehouse.py` da `inventory_confirm` ichida 1430–1440-qatorlarni quyidagiga almashtiring:

```python
    form = await request.form()
    doc_date_str = form.get("doc_date")
    if doc_date_str:
        parsed = _parse_doc_date(doc_date_str)
        if parsed:
            doc.date = parsed
    # YANGI: tur doc.type'dan; POST'da qayta tasdiq
    posted_type = (form.get("type") or "").strip()
    doc_type = (doc.type or "inventory")
    if posted_type and posted_type != doc_type:
        # Atomik UPDATE'ni qaytarish: status'ni qayta 'draft' qilish
        db.execute(
            _text("UPDATE stock_adjustment_docs SET status='draft' WHERE id=:id"),
            {"id": doc_id},
        )
        db.commit()
        return RedirectResponse(
            url=f"/inventory/{doc_id}/edit?message=Tur mos kelmadi, sahifani yangilang.",
            status_code=303,
        )
    is_stock_entry = (doc_type == "stock_entry")
    if is_stock_entry and doc.date:
        date_str = doc.date.strftime("%Y%m%d")
        doc.number = _next_inventory_number(db, date_str)
```

(Diff: 1437-qatordagi `is_stock_entry = bool(doc.number ... INV-PENDING)` o'rniga yuqoridagi; oldingi `doc_date_str` parsing'i avvalgi joyiga qoldiriladi.)

- [ ] **Step 6.2: Tur ustuni ensure helper'ini chaqirish**

`inventory_confirm` boshida (1414-qator atrofida, `if not current_user` dan keyin) qo'shing:
```python
    from app.utils.db_schema import ensure_stock_adjustment_doc_type_column
    ensure_stock_adjustment_doc_type_column(db)
```

- [ ] **Step 6.3: Run testlar**

Run: `python -m pytest tests/test_inventory_type.py tests/test_inventory_type_switch.py tests/test_inventory_confirm_baseline.py -v`
Expected: hammasi PASS.

- [ ] **Step 6.4: Commit**

```bash
git add app/routes/warehouse.py
git commit -m "fix(inventory): D1 — inventory_confirm is_stock_entry doc.type'dan (POST tasdig'i bilan)

Eski: number.startswith('INV-PENDING') — re-confirm'da semantika ag'darilardi.
Yangi: doc.type ('inventory'|'stock_entry'). Form'da posted type doc.type
bilan solishtiriladi; mos kelmasa status='draft' qaytariladi, yozuv yo'q."
```

---

## Task 7: `inventory_create_draft` Form'dan `type` qabul qilish

**Files:**
- Modify: `app/routes/warehouse.py:978-1018` (`inventory_create_draft`)

- [ ] **Step 7.1: `type` parametri va doc atributi**

`inventory_create_draft` signaturasiga `type` ni qo'shing va doc yaratishda ishlatilsin:
```python
@inventory_router.post("/create-draft")
async def inventory_create_draft(
    warehouse_id: int = Form(...),
    force_new: int = Form(0),
    type: str = Form("inventory"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    from app.utils.db_schema import ensure_stock_adjustment_doc_type_column
    ensure_stock_adjustment_doc_type_column(db)
    if type not in ("inventory", "stock_entry"):
        type = "inventory"
    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        return RedirectResponse(url="/inventory/new?message=Ombor topilmadi.", status_code=303)
    from app.utils.draft_check import redirect_to_draft
    redirect = redirect_to_draft(
        db, StockAdjustmentDoc,
        edit_url_template="/inventory/{id}/edit",
        user_role=getattr(current_user, "role", "") or "",
        force_new=bool(force_new),
        message=f"Sizda ushbu omborga ({wh.name}) ochiq qoralama bor — avval uni tugating yoki bekor qiling.",
        user_id=current_user.id,
        warehouse_id=warehouse_id,
    )
    if redirect:
        return redirect
    today = datetime.now()
    doc = StockAdjustmentDoc(
        number="INV-PENDING",
        date=today,
        warehouse_id=warehouse_id,
        user_id=current_user.id,
        status="draft",
        type=type,
        total_tannarx=0,
        total_sotuv=0,
    )
    db.add(doc)
    db.flush()
    doc.number = f"INV-PENDING-{doc.id}"
    db.commit()
    db.refresh(doc)
    return RedirectResponse(url=f"/inventory/{doc.id}/edit", status_code=303)
```

- [ ] **Step 7.2: Commit**

```bash
git add app/routes/warehouse.py
git commit -m "feat(inventory): create-draft Form'dan type qabul qiladi (default inventory)"
```

---

## Task 8: UI — `inventory/new.html` tur radio

**Files:**
- Modify: `app/templates/inventory/new.html:25-40`

- [ ] **Step 8.1: Forma'ga radio qo'shish**

`<form method="post" action="/inventory/create-draft" ...>` ichida `warehouse_id` select'idan keyin, submit tugmasidan oldin yangi qator qo'shing:
```html
            <div class="col-md-12">
                <label class="form-label fw-600">Hujjat turi</label>
                <div class="d-flex flex-column gap-2">
                    <label class="form-check">
                        <input class="form-check-input" type="radio" name="type" value="inventory" checked>
                        <span class="form-check-label">
                            <strong>Inventarizatsiya</strong>
                            <small class="text-muted d-block">Jismoniy sanoq — qoldiq aynan kiritilgan songa o'rnatiladi.</small>
                        </span>
                    </label>
                    <label class="form-check">
                        <input class="form-check-input" type="radio" name="type" value="stock_entry">
                        <span class="form-check-label">
                            <strong>Tovar qoldiqlari</strong>
                            <small class="text-muted d-block">Yangi partiya — kiritilgan son mavjud qoldiq ustiga qo'shiladi.</small>
                        </span>
                    </label>
                </div>
            </div>
```

- [ ] **Step 8.2: Qo'lda smoke (TestClient yoki manual)**

Optional manual: serverni dev port'da ishga tushirib `/inventory/new` ochish va ikkala radio ishlashini ko'rish. (Live prod'da emas.)

- [ ] **Step 8.3: Commit**

```bash
git add app/templates/inventory/new.html
git commit -m "feat(inventory): /inventory/new — tur radio (default Inventarizatsiya)"
```

---

## Task 9: UI — `inventory/edit.html` tur badge + confirm tasdig'i

**Files:**
- Modify: `app/templates/inventory/edit.html`

- [ ] **Step 9.1: Joriy confirm tugmasini topish**

Run: `grep -n 'confirm\|Tasdiq\|tasdiq\|type="submit"' "app/templates/inventory/edit.html"`
Confirm forma'sini (action `.../confirm` bilan) toping.

- [ ] **Step 9.2: Sahifa tepasiga tur badge qo'shish**

`<div class="page-header...` blokining ostiga (tasdiq formasidan oldin) qo'shing:
```html
{% set _is_stock_entry = (doc.type == 'stock_entry') %}
<div class="alert {% if _is_stock_entry %}alert-warning{% else %}alert-info{% endif %} py-2 small mb-3">
  <i class="bi bi-{% if _is_stock_entry %}plus-circle{% else %}clipboard-check{% endif %}"></i>
  <strong>{% if _is_stock_entry %}Tovar qoldiqlari{% else %}Inventarizatsiya{% endif %}</strong> —
  {% if _is_stock_entry %}
    kiritilgan son mavjud qoldiq <strong>ustiga qo'shiladi</strong>.
  {% else %}
    qoldiq <strong>aynan</strong> kiritilgan songa o'rnatiladi.
  {% endif %}
</div>
```

- [ ] **Step 9.3: Confirm formaga yashirin `type` va matn moslash**

Confirm `<form action="/inventory/{{ doc.id }}/confirm" method="post">` ichiga (`</form>` dan oldin) qo'shing:
```html
<input type="hidden" name="type" value="{{ doc.type or 'inventory' }}">
```
Va confirm tugmasi matnini turga moslang:
```html
<button type="submit" class="...">
  <i class="bi bi-check-circle me-1"></i>
  {% if doc.type == 'stock_entry' %}Tovar qoldiqlari sifatida tasdiqlash{% else %}Inventarizatsiya sifatida tasdiqlash{% endif %}
</button>
```

- [ ] **Step 9.4: Commit**

```bash
git add app/templates/inventory/edit.html
git commit -m "feat(inventory): edit.html — tur badge + confirm yashirin type + matn moslash"
```

---

## Task 10: UI — `inventory/list.html` va `inventory/view.html` tur badge

**Files:**
- Modify: `app/templates/inventory/list.html`
- Modify: `app/templates/inventory/view.html`

- [ ] **Step 10.1: Ro'yxat ustuni**

`inventory/list.html` da hujjatlar jadvalida (`<thead>` va `<tbody>` qatorlarini topib) yangi ustun qo'shing:

Header'ga:
```html
<th>Turi</th>
```
Har qatorga (loop ichida):
```html
<td>
  {% if doc.type == 'stock_entry' %}
    <span class="badge bg-warning text-dark">Tovar qoldiqlari</span>
  {% else %}
    <span class="badge bg-info">Inventarizatsiya</span>
  {% endif %}
</td>
```

- [ ] **Step 10.2: View sahifa badge**

`inventory/view.html` sahifa header'iga (status badge yonida) qo'shing:
```html
{% if doc.type == 'stock_entry' %}
  <span class="badge bg-warning text-dark">Tovar qoldiqlari</span>
{% else %}
  <span class="badge bg-info">Inventarizatsiya</span>
{% endif %}
```

- [ ] **Step 10.3: Commit**

```bash
git add app/templates/inventory/list.html app/templates/inventory/view.html
git commit -m "feat(inventory): list/view sahifalarda tur badge"
```

---

## Task 11: Backfill skript (eski hujjatlarga `type` qiymati)

**Files:**
- Create: `scripts/backfill_inventory_type.py`

- [ ] **Step 11.1: Skript yozish (sentinel + dry-run + apply)**

`scripts/backfill_inventory_type.py` yarating:
```python
"""Eski StockAdjustmentDoc hujjatlariga 'type' qiymatini backfill qiladi.

Manba: stock_movements.note (haqiqiy bajarilgan semantika), CHUNKI doc.number
confirm'da qayta nomlanadi (INV-PENDING -> INV-YYYYMMDD).

ISHLATISH:
  python backfill_inventory_type.py             # DRY-RUN (default)
  python backfill_inventory_type.py --apply     # backup + bitta tranzaksiya
"""
import sys, os, shutil, sqlite3, datetime

ARGS = sys.argv[1:]
APPLY = "--apply" in ARGS
CANDIDATES = [
    r"\\server2220\d\TOTLI BI\totli_holva.db",
    r"D:\TOTLI BI\totli_holva.db",
]
# Sentinel: ustun mavjudligini tasdiqlash
SENTINEL_TABLE = "stock_adjustment_docs"
SENTINEL_COL = "type"


def find_db():
    for p in CANDIDATES:
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            continue
        try:
            con = sqlite3.connect(p)
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({SENTINEL_TABLE})")}
            con.close()
            if SENTINEL_COL in cols:
                return p
        except Exception:
            pass
    return None


def classify(notes, number):
    notes = [n or "" for n in notes]
    if any(n.startswith(("Tovar qoldiqlari", "Qoldiq kiritish")) for n in notes):
        return "stock_entry"
    if any(n.startswith("Inventarizatsiya") for n in notes):
        return "inventory"
    if (number or "").startswith("QLD"):
        return "stock_entry"
    return "inventory"


def main():
    db = find_db()
    if not db:
        print(f"XATO: jonli DB topilmadi yoki '{SENTINEL_COL}' ustuni hali qo'shilmagan.")
        sys.exit(1)
    print(f"DB: {db}")
    print(f"Rejim: {'APPLY' if APPLY else 'DRY-RUN'}")
    print("=" * 70)

    if APPLY:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = f"{db}.pre-typebackfill.{ts}.bak"
        shutil.copy2(db, bak)
        print(f"Backup: {bak}")

    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    c = con.cursor()
    docs = c.execute(
        "SELECT id, number, COALESCE(type,'') FROM stock_adjustment_docs ORDER BY id"
    ).fetchall()
    plan = {"inventory": 0, "stock_entry": 0, "unchanged": 0}
    samples = []
    updates = []
    for doc_id, number, cur_type in docs:
        notes = [r[0] for r in c.execute(
            "SELECT note FROM stock_movements WHERE document_type='StockAdjustmentDoc' AND document_id=?",
            (doc_id,)
        ).fetchall()]
        new_type = classify(notes, number)
        if cur_type == new_type:
            plan["unchanged"] += 1
            continue
        plan[new_type] += 1
        updates.append((new_type, doc_id))
        if len(samples) < 10:
            samples.append((doc_id, number, cur_type, new_type))
    print(f"Jami: {len(docs)} | yangilanadi inventory: {plan['inventory']} | "
          f"stock_entry: {plan['stock_entry']} | o'zgarmaydi: {plan['unchanged']}")
    print("Namuna 10 ta:")
    for s in samples:
        print(f"  doc#{s[0]} number={s[1]!r} {s[2]!r} -> {s[3]!r}")
    if not APPLY:
        print("=" * 70)
        print("DRY-RUN tugadi. Yozish:  python backfill_inventory_type.py --apply")
        con.close()
        return
    try:
        c.execute("BEGIN IMMEDIATE")
        for new_type, doc_id in updates:
            c.execute(
                "UPDATE stock_adjustment_docs SET type=? WHERE id=?",
                (new_type, doc_id),
            )
        con.commit()
        print(f"COMMIT OK. {len(updates)} hujjat yangilandi.")
    except Exception as e:
        con.rollback()
        print(f"!!! XATO -> ROLLBACK: {type(e).__name__}: {e}")
        sys.exit(4)
    finally:
        con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 11.2: Skriptning dry-run mantiqi uchun unit test (in-memory)**

`tests/test_inventory_type_backfill.py` yarating:
```python
"""Backfill classify() funksiyasi unit testlari."""
import importlib.util, pathlib

# Skriptni modul sifatida yuklash
_path = pathlib.Path(__file__).parent.parent / "scripts" / "backfill_inventory_type.py"
spec = importlib.util.spec_from_file_location("backfill_inventory_type", _path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
classify = mod.classify


def test_stock_entry_from_note():
    assert classify(["Tovar qoldiqlari: INV-X"], "INV-X") == "stock_entry"


def test_inventory_from_note():
    assert classify(["Inventarizatsiya: INV-X"], "INV-X") == "inventory"


def test_qld_prefix_when_no_notes():
    assert classify([], "QLD-20260507-0001") == "stock_entry"


def test_default_inventory():
    assert classify([], "INV-PENDING-99") == "inventory"
    assert classify([], None) == "inventory"
```

Run: `python -m pytest tests/test_inventory_type_backfill.py -v`
Expected: 4 passed.

- [ ] **Step 11.3: Commit**

```bash
git add scripts/backfill_inventory_type.py tests/test_inventory_type_backfill.py
git commit -m "feat(inventory): backfill skript (note'dan type, sentinel + dry-run + apply)"
```

---

## Task 12: Smoke + deploy checklist (tungi oyna)

Bu task kod yozish emas — deploy daqiqasidagi checklist. Tasdiqlash uchun.

- [ ] **Step 12.1: Mahalliy to'liq testlar yashil**

Run: `python -m pytest tests/test_inventory_type.py tests/test_inventory_type_switch.py tests/test_inventory_confirm_baseline.py tests/test_inventory_type_backfill.py -v`
Expected: hammasi PASS.

Run: `python -m pytest tests/ -v --ignore=tests/test_endpoints_smoke.py 2>&1 | tail -30`
Expected: yangi yiqilish yo'q (eski stale failures avvalgi kabi).

- [ ] **Step 12.2: PR / merge tayyor**

```bash
git push -u origin feat-inventory-type-baseline
# GitHub PR -> main (yoki feat-bulk-dispatch base, branch holatiga qarab)
```

- [ ] **Step 12.3: Tungi oyna deploy ketma-ketligi (server2220 RDP)**

1. **Backup:** standart `.bak` (live backup tizimi avtomatik, lekin qo'lda ham: `copy "totli_holva.db" "totli_holva.db.pre-invtype.YYYYMMDD_HHMMSS.bak"`).
2. **Merge:** `git checkout main; git pull; git merge --no-ff feat-inventory-type-baseline; git push`.
3. **Restart:** `taskkill /IM python.exe /F && start.bat`. `ensure_stock_adjustment_doc_type_column` birinchi `/inventory/...` so'rovida ustunni qo'shadi (yoki bootstrap shu yerga qo'shilmagan bo'lsa qo'lda: `python -c "from app.database import SessionLocal; from app.utils.db_schema import ensure_stock_adjustment_doc_type_column as f; db=SessionLocal(); f(db); db.close()"`).
4. **Backfill DRY-RUN:** `python scripts/backfill_inventory_type.py` — natija ko'rish, tasdiq.
5. **Backfill APPLY:** `python scripts/backfill_inventory_type.py --apply` — `.bak` yaratiladi.
6. **Smoke (browser yoki TestClient):**
   - `/inventory/new` — ikkala radio ko'rinadi
   - Inventarizatsiya draft yaratish → tovar yuklash → tasdiq → Stock jismoniy songa o'rnatiladi
   - Tovar qoldiqlari draft yaratish → tovar yuklash → tasdiq → Stock mavjud + jismoniy
   - `/inventory` ro'yxatida tur badge ko'rinadi
7. **Verify:** post-deploy script — manfiy Stock yo'q, oxirgi 2 hujjat tur'lari to'g'ri.

- [ ] **Step 12.4: Rollback rejasi (kerak bo'lsa)**

- Kod: `git revert <merge-commit>`; restart.
- Data: `type` ustuni qoladi (eski kod uni o'qimaydi). Backfill qaytarish kerak bo'lsa `.bak` dan tiklash yoki `UPDATE stock_adjustment_docs SET type=NULL` (eski kodga zarar yo'q).

---

## Self-Review natijasi

**Spec qamrovi tekshiruvi:**
- Spec §1 (kontekst) — Task 1, 3, 5 testlari qamraydi
- Spec §2 (qamrov) — barcha tasklar `/inventory/` doirasida; `/qoldiqlar/` tegilmaydi
- Spec §3 (yondashuv A) — Tasklar 1–11 amalga oshiradi
- Spec §4 (data model + migration) — Task 1 (model), Task 2 (ensure helper), Task 11 (backfill)
- Spec §5 (confirm logikasi) — Task 4 (D2 baseline), Task 6 (D1 type)
- Spec §6 (UI oqimi) — Tasklar 7–10
- Spec §7 (xatolar) — Task 6 (NULL default, POST mismatch), Task 4 (multi-warehouse), atomiklik o'zgarmagan
- Spec §8 (test) — Tasklar 3, 5, 11.2 + Task 12 smoke
- Spec §9 (tier/deploy) — Task 12

**Placeholder skani:** Kod bloklari to'liq; "TBD" yo'q; xato xabarlar aniq matnli.

**Tur izchilligi:** `doc.type` har joyda `'inventory'`/`'stock_entry'`; `is_stock_entry: bool` parametr nomi `_apply_inventory_stock_changes` da o'zgarmaydi.

**Boshqaruv buyrug'i:** `python -m pytest` shaklida (loyiha conftest path'i to'g'ri ishlashi uchun).
