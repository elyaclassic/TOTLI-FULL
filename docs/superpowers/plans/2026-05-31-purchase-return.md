# Yetkazib beruvchiga qaytarish (Purchase Return) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Yetkazib beruvchiga brak/yaroqsiz mahsulotni qaytarish uchun atomik hujjat (stock chiqim + yetkazib beruvchi qarzini kamaytirish + audit) qurish.

**Architecture:** Yangi `PurchaseReturn`/`PurchaseReturnItem` modellari (Purchase'ga parallel, izolyatsiyalangan). Confirm/cancel mantig'i yangi `purchase_return_service.py` da, `document_service.py` xarid-confirm naqshining teskarisi. Reconciliation (`_build_partner_movements`) ga additive blok. Yangi `purchase_returns.py` router + templatelar.

**Tech Stack:** FastAPI, SQLAlchemy (SQLite), Jinja2, pytest. Spec: `docs/superpowers/specs/2026-05-31-purchase-return-design.md`.

---

## File Structure

- `app/models/database.py` — `PurchaseReturn`, `PurchaseReturnItem` modellari (Purchase yonida)
- `app/utils/db_schema.py` — `ensure_purchase_return_tables(db)` helper
- `app/services/purchase_return_service.py` — **YANGI**: `confirm_return`, `cancel_return`, `validate_return`
- `app/routes/purchase_returns.py` — **YANGI**: router (list/new/create/detail/confirm/cancel + price API)
- `app/templates/purchase_returns/{list,new,detail}.html` — **YANGI**
- `app/routes/reports.py` — `_build_partner_movements` ga additive blok
- `app/main.py` — router include + startup'da ensure helper
- `app/templates/base.html` — navbar havola
- `tests/test_purchase_return.py` — **YANGI**: testlar

---

## Task 1: Data modellari + jadval helper

**Files:**
- Modify: `app/models/database.py` (Purchase blokidan keyin, ~line 124)
- Modify: `app/utils/db_schema.py` (oxiriga qo'shish)
- Test: `tests/test_purchase_return.py`

- [ ] **Step 1: Failing test — modellar import bo'ladi va jadval yaratiladi**

```python
# tests/test_purchase_return.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.database import Base, PurchaseReturn, PurchaseReturnItem, Partner, Warehouse, Product, Stock, Unit

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()

def test_models_exist_and_persist(db):
    pr = PurchaseReturn(number="PR-20260531-0001", partner_id=1, warehouse_id=1,
                        status="draft", reason="brak", total=0.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=2.0, price=1000.0, total=2000.0))
    db.commit()
    got = db.query(PurchaseReturn).first()
    assert got.number == "PR-20260531-0001"
    assert got.items[0].total == 2000.0
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_purchase_return.py::test_models_exist_and_persist -v`
Expected: FAIL — `ImportError: cannot import name 'PurchaseReturn'`

- [ ] **Step 3: Modellarni qo'shish** (`database.py`, PurchaseExpense'dan keyin ~line 124)

```python
class PurchaseReturn(Base):
    """Yetkazib beruvchiga qaytarish hujjati (brak/yaroqsiz)"""
    __tablename__ = "purchase_returns"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(40), unique=True, index=True)
    date = Column(DateTime, default=datetime.now)
    partner_id = Column(Integer, ForeignKey("partners.id"))
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    status = Column(String(20), default="draft")  # draft | confirmed | cancelled
    reason = Column(String(20), default="brak")    # brak | expired | other
    total = Column(Float, default=0)
    notes = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    items = relationship("PurchaseReturnItem", back_populates="return_doc",
                         cascade="all, delete-orphan")
    partner = relationship("Partner")
    warehouse = relationship("Warehouse")

    __table_args__ = (
        Index("idx_purchase_returns_user_status", "user_id", "status"),
    )


class PurchaseReturnItem(Base):
    """Qaytarish qatorlari"""
    __tablename__ = "purchase_return_items"
    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("purchase_returns.id"), index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    quantity = Column(Float)
    price = Column(Float)
    total = Column(Float)
    return_doc = relationship("PurchaseReturn", back_populates="items")
    product = relationship("Product")
```

- [ ] **Step 4: Run test, verify it passes**

Run: `python -m pytest tests/test_purchase_return.py::test_models_exist_and_persist -v`
Expected: PASS

- [ ] **Step 5: `ensure_purchase_return_tables` helper** (`db_schema.py` oxiriga)

```python
def ensure_purchase_return_tables(db: Session) -> None:
    """purchase_returns + purchase_return_items jadvallari (yetkazib beruvchiga qaytarish)."""
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number VARCHAR(40) UNIQUE,
                date DATETIME,
                partner_id INTEGER REFERENCES partners(id),
                warehouse_id INTEGER REFERENCES warehouses(id),
                status VARCHAR(20) DEFAULT 'draft',
                reason VARCHAR(20) DEFAULT 'brak',
                total FLOAT DEFAULT 0,
                notes TEXT,
                user_id INTEGER REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_return_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                return_id INTEGER REFERENCES purchase_returns(id),
                product_id INTEGER REFERENCES products(id),
                quantity FLOAT,
                price FLOAT,
                total FLOAT
            )
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pr_user_status ON purchase_returns(user_id, status)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pri_return ON purchase_return_items(return_id)"))
        db.commit()
    except Exception:
        db.rollback()
```

- [ ] **Step 6: Commit**

```bash
git add app/models/database.py app/utils/db_schema.py tests/test_purchase_return.py
git commit -m "feat(purchase-return): PurchaseReturn/PurchaseReturnItem modellari + jadval helper"
```

---

## Task 2: Confirm mantig'i (stock chiqim + balans)

**Files:**
- Create: `app/services/purchase_return_service.py`
- Test: `tests/test_purchase_return.py`

**Eslatma:** `confirm_return` xarid-confirm (`document_service.py:114-152`) naqshining teskarisi: stock `-qty`, `partner.balance += total`, `purchase_price` ga TEGILMAYDI.

- [ ] **Step 1: Failing test — confirm stock'ni kamaytiradi va qarzni kamaytiradi**

```python
def _seed(db):
    db.add(Unit(id=1, name="dona", code="ta"))
    db.add(Warehouse(id=1, name="Xom ashyo ombori"))
    db.add(Product(id=1, name="Yong'oq", unit_id=1, purchase_price=1000.0))
    db.add(Partner(id=1, name="Shakar aka", type="supplier", balance=-50000.0))  # biz 50k qarzdormiz
    db.add(Stock(warehouse_id=1, product_id=1, quantity=10.0))
    db.commit()

def test_confirm_reduces_stock_and_debt(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return
    pr = PurchaseReturn(number="PR-20260531-0001", partner_id=1, warehouse_id=1,
                        date=__import__("datetime").datetime(2026,5,31,10,0), status="draft",
                        reason="brak", total=3000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=3.0, price=1000.0, total=3000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    db.refresh(pr)
    assert pr.status == "confirmed"
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 7.0  # 10-3
    assert db.query(Partner).get(1).balance == -47000.0  # -50000 + 3000 (qarz kamaydi)
    assert db.query(Product).get(1).purchase_price == 1000.0  # TEGILMAGAN
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_purchase_return.py::test_confirm_reduces_stock_and_debt -v`
Expected: FAIL — `ModuleNotFoundError: app.services.purchase_return_service`

- [ ] **Step 3: Service yaratish**

```python
# app/services/purchase_return_service.py
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.database import PurchaseReturn, PurchaseReturnItem, Partner, Stock
from app.services.stock_service import create_stock_movement


class DocumentError(Exception):
    pass


def validate_return(db: Session, doc: PurchaseReturn) -> None:
    """Tasdiqlash oldidan tekshiruvlar. Xato bo'lsa DocumentError."""
    items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == doc.id).all()
    if not items:
        raise DocumentError("Hujjatda qator yo'q")
    for it in items:
        if not it.quantity or it.quantity <= 0:
            raise DocumentError("Miqdor 0 dan katta bo'lishi kerak")
        stock = db.query(Stock).filter(
            Stock.warehouse_id == doc.warehouse_id,
            Stock.product_id == it.product_id,
        ).first()
        have = float(stock.quantity or 0) if stock else 0.0
        if have < float(it.quantity) - 1e-6:
            raise DocumentError(
                f"Omborda yetarli emas (mahsulot {it.product_id}): "
                f"{have:,.2f} mavjud, {it.quantity:,.2f} qaytarilmoqchi"
            )


def confirm_return(db: Session, doc: PurchaseReturn, current_user=None, client_host=None) -> None:
    """Atomik: stock chiqim + yetkazib beruvchi qarzini kamaytirish + audit."""
    # Double-confirm himoyasi
    res = db.execute(
        text("UPDATE purchase_returns SET status='confirmed' WHERE id=:id AND status='draft'"),
        {"id": doc.id},
    )
    if res.rowcount == 0:
        db.rollback()
        raise DocumentError("Hujjat allaqachon tasdiqlangan yoki bekor qilingan")
    try:
        validate_return(db, doc)
        items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == doc.id).all()
        for it in items:
            create_stock_movement(
                db=db,
                warehouse_id=doc.warehouse_id,
                product_id=it.product_id,
                quantity_change=-float(it.quantity),
                operation_type="return_purchase",
                document_type="PurchaseReturn",
                document_id=doc.id,
                document_number=doc.number,
                user_id=current_user.id if current_user else None,
                note=f"Yetkazib beruvchiga qaytarish: {doc.number}",
                created_at=doc.date,
            )
        if doc.partner_id:
            partner = db.query(Partner).filter(Partner.id == doc.partner_id).first()
            if partner:
                partner.balance = (partner.balance or 0) + float(doc.total or 0)
        try:
            from app.utils.audit import log_action
            log_action(db, user=current_user, action="confirm",
                       entity_type="purchase_return", entity_id=doc.id,
                       entity_number=doc.number, details=f"Summa: {doc.total:,.0f}",
                       ip_address=client_host or "")
        except Exception:
            pass
        db.commit()
    except DocumentError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
```

> **Eslatma:** `log_action` importi `app/utils/audit.py` da. Agar yo'l boshqacha bo'lsa, `document_service.py` dagi `log_action` importini nusxalang. try/except bilan o'ralgani sababli audit xato confirm'ni buzmaydi.

- [ ] **Step 4: Run test, verify it passes**

Run: `python -m pytest tests/test_purchase_return.py::test_confirm_reduces_stock_and_debt -v`
Expected: PASS

- [ ] **Step 5: Failing test — ombordan ko'p qaytarib bo'lmaydi + double-confirm**

```python
def test_cannot_return_more_than_stock(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return, DocumentError
    pr = PurchaseReturn(number="PR-20260531-0002", partner_id=1, warehouse_id=1,
                        date=__import__("datetime").datetime(2026,5,31,10,0), status="draft", total=99000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=99.0, price=1000.0, total=99000.0))
    db.commit()
    with pytest.raises(DocumentError):
        confirm_return(db, pr, current_user=None)
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 10.0  # o'zgarmagan

def test_double_confirm_blocked(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return, DocumentError
    pr = PurchaseReturn(number="PR-20260531-0003", partner_id=1, warehouse_id=1,
                        date=__import__("datetime").datetime(2026,5,31,10,0), status="draft", total=1000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=1.0, price=1000.0, total=1000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    with pytest.raises(DocumentError):
        confirm_return(db, pr, current_user=None)
    assert db.query(Partner).get(1).balance == -49000.0  # faqat 1 marta (-50000+1000)
```

- [ ] **Step 6: Run, verify pass** (mantiq Step 3 da yozilgan; rollback validatsiyadan oldin status'ni qaytarishi kerak)

Run: `python -m pytest tests/test_purchase_return.py -v`
Expected: hammasi PASS. **Agar `test_cannot_return_more_than_stock` FAIL bo'lsa** (status='confirmed' qolib ketgan bo'lsa), `validate_return` ni atomik UPDATE'dan OLDIN chaqiring yoki validatsiya xatosida `UPDATE ... SET status='draft'` bilan qaytaring. To'g'ri tartib: avval `validate_return(db, doc)`, keyin atomik UPDATE, keyin stock/balans.

> **TUZATISH (Step 3 ni yangilang):** `validate_return(db, doc)` ni double-confirm UPDATE'dan **oldin** chaqiring, shunda validatsiya xatosida status `draft` qoladi:
> ```python
> validate_return(db, doc)  # avval — xato bo'lsa status draft qoladi
> res = db.execute(text("UPDATE purchase_returns SET status='confirmed' WHERE id=:id AND status='draft'"), {"id": doc.id})
> if res.rowcount == 0:
>     db.rollback(); raise DocumentError("Allaqachon tasdiqlangan")
> # keyin stock + balans + audit + commit
> ```

- [ ] **Step 7: Commit**

```bash
git add app/services/purchase_return_service.py tests/test_purchase_return.py
git commit -m "feat(purchase-return): confirm_return + validate (stock chiqim, balans, double-confirm)"
```

---

## Task 3: Bekor qilish (cancel/revert)

**Files:**
- Modify: `app/services/purchase_return_service.py`
- Test: `tests/test_purchase_return.py`

- [ ] **Step 1: Failing test — bekor stock va balansni tiklaydi**

```python
def test_cancel_restores(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return, cancel_return
    pr = PurchaseReturn(number="PR-20260531-0004", partner_id=1, warehouse_id=1,
                        date=__import__("datetime").datetime(2026,5,31,10,0), status="draft", total=2000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=2.0, price=1000.0, total=2000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 8.0
    cancel_return(db, pr, current_user=None)
    db.refresh(pr)
    assert pr.status == "cancelled"
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 10.0  # tiklandi
    assert db.query(Partner).get(1).balance == -50000.0  # tiklandi
```

- [ ] **Step 2: Run, verify fails** (`ImportError: cancel_return`)

Run: `python -m pytest tests/test_purchase_return.py::test_cancel_restores -v`

- [ ] **Step 3: `cancel_return` qo'shish**

```python
def cancel_return(db: Session, doc: PurchaseReturn, current_user=None, client_host=None) -> None:
    """Tasdiqlangan qaytarishni bekor qilish — stock va balansni tiklaydi."""
    res = db.execute(
        text("UPDATE purchase_returns SET status='cancelled' WHERE id=:id AND status='confirmed'"),
        {"id": doc.id},
    )
    if res.rowcount == 0:
        db.rollback()
        raise DocumentError("Faqat tasdiqlangan hujjatni bekor qilish mumkin")
    try:
        items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == doc.id).all()
        for it in items:
            create_stock_movement(
                db=db, warehouse_id=doc.warehouse_id, product_id=it.product_id,
                quantity_change=+float(it.quantity), operation_type="return_purchase_revert",
                document_type="PurchaseReturn", document_id=doc.id, document_number=doc.number,
                user_id=current_user.id if current_user else None,
                note=f"Qaytarish bekor qilindi: {doc.number}", created_at=doc.date,
            )
        if doc.partner_id:
            partner = db.query(Partner).filter(Partner.id == doc.partner_id).first()
            if partner:
                partner.balance = (partner.balance or 0) - float(doc.total or 0)
        db.commit()
    except Exception:
        db.rollback()
        raise
```

- [ ] **Step 4: Run, verify passes**

Run: `python -m pytest tests/test_purchase_return.py -v`
Expected: hammasi PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/purchase_return_service.py tests/test_purchase_return.py
git commit -m "feat(purchase-return): cancel_return (stock+balans tiklash)"
```

---

## Task 4: Reconciliation integratsiyasi

**Files:**
- Modify: `app/routes/reports.py::_build_partner_movements` (~line 2036, `rows.sort` dan oldin)
- Test: `tests/test_purchase_return.py`

- [ ] **Step 1: Failing test — qaytarish reconciliation'da DEBIT**

```python
def test_reconciliation_includes_return_as_debit(db):
    # _build_partner_movements DB-bog'liq; bu yerda faqat blok mantig'ini tekshiramiz:
    # tasdiqlangan PurchaseReturn -> debit=total, credit=0
    _seed(db)
    from app.services.purchase_return_service import confirm_return
    pr = PurchaseReturn(number="PR-20260531-0005", partner_id=1, warehouse_id=1,
                        date=__import__("datetime").datetime(2026,5,15,10,0), status="draft", total=4000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=4.0, price=1000.0, total=4000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    # blok mantig'i (reports.py ga ko'chiriladi):
    confirmed = db.query(PurchaseReturn).filter(
        PurchaseReturn.partner_id == 1, PurchaseReturn.status == "confirmed").all()
    rows = [{"date": d.date, "doc_type": "Xarid qaytarish", "debit": float(d.total or 0), "credit": 0.0}
            for d in confirmed]
    assert rows and rows[0]["debit"] == 4000.0 and rows[0]["credit"] == 0.0
```

- [ ] **Step 2: Run, verify passes** (bu test blok mantig'ini mustaqil tekshiradi — Step 1 da PASS bo'ladi, chunki mantiq inline). Asl maqsad: shu blokni `reports.py` ga qo'shish.

Run: `python -m pytest tests/test_purchase_return.py::test_reconciliation_includes_return_as_debit -v`
Expected: PASS

- [ ] **Step 3: `_build_partner_movements` ga blok qo'shish** (`reports.py`, xarid bloki (~line 2006) dan keyin, `rows.sort` (~line 2038) dan oldin)

```python
    # Yetkazib beruvchiga qaytarishlar (tasdiqlangan) — xaridning teskarisi: DEBIT
    from app.models.database import PurchaseReturn as _PR
    q_returns = db.query(_PR).filter(
        _PR.partner_id == partner_id,
        _PR.status == "confirmed",
    )
    if period_only:
        q_returns = q_returns.filter(_PR.date >= date_from_start, _PR.date <= date_to_end)
    for d in q_returns.order_by(_PR.date):
        doc_label = f"Xarid qaytarish {d.number or ''} {d.date.strftime('%d.%m.%Y %H:%M') if d.date else ''}".strip()
        rows.append({
            "date": d.date,
            "doc_type": "Xarid qaytarish",
            "doc_number": d.number or "",
            "doc_label": doc_label,
            "doc_url": f"/purchase-returns/{d.id}",
            "debit": float(d.total or 0),
            "credit": 0.0,
        })
```

- [ ] **Step 4: Verify** — `python -c "import app.routes.reports"` xatosiz; smoke (Task 7) da reconciliation tekshiriladi.

Run: `python -c "import ast; ast.parse(open(r'app/routes/reports.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add app/routes/reports.py tests/test_purchase_return.py
git commit -m "feat(purchase-return): reconciliation'ga 'Xarid qaytarish' DEBIT bloki"
```

---

## Task 5: Router (list/new/create/detail/confirm/cancel + price API)

**Files:**
- Create: `app/routes/purchase_returns.py`
- Reference: `app/routes/purchases.py` (raqam-gen ~line 207, create ~line 230)

- [ ] **Step 1: Router skeleti** (auth, rol admin/manager, get_db naqshi `purchases.py` dan)

```python
# app/routes/purchase_returns.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
from app.core import templates            # purchases.py qaysi modulldan import qilsa — shuni ishlat
from app.deps import get_db, require_auth  # purchases.py bilan bir xil
from app.models.database import PurchaseReturn, PurchaseReturnItem, Partner, Warehouse, Product, Stock
from app.services.purchase_return_service import confirm_return, cancel_return, DocumentError

router = APIRouter(prefix="/purchase-returns", tags=["purchase-returns"])


def _require_manager(user):
    return user and user.role in ("admin", "manager")
```

> **Eslatma:** `templates`, `get_db`, `require_auth` importlarini `app/routes/purchases.py` ning yuqorisidan AYNAN nusxalang (loyihada yo'llar farq qilishi mumkin).

- [ ] **Step 2: List + new + create**

```python
@router.get("", response_class=HTMLResponse)
async def pr_list(request: Request, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    if not _require_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    docs = db.query(PurchaseReturn).order_by(PurchaseReturn.id.desc()).limit(200).all()
    return templates.TemplateResponse("purchase_returns/list.html",
                                      {"request": request, "docs": docs, "current_user": current_user})

@router.get("/new", response_class=HTMLResponse)
async def pr_new(request: Request, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    if not _require_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    suppliers = db.query(Partner).filter(Partner.is_active == True,
                                         Partner.type.in_(["supplier", "both"])).order_by(Partner.name).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name).all()
    products = db.query(Product).order_by(Product.name).all()
    return templates.TemplateResponse("purchase_returns/new.html",
        {"request": request, "suppliers": suppliers, "warehouses": warehouses,
         "products": products, "current_user": current_user})

@router.get("/price", response_class=JSONResponse)
async def pr_price(product_id: int, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    p = db.query(Product).filter(Product.id == product_id).first()
    return {"price": float((p.purchase_price if p else 0) or 0)}

@router.post("")
async def pr_create(request: Request, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    if not _require_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    form = await request.form()
    partner_id = int(form.get("partner_id"))
    warehouse_id = int(form.get("warehouse_id"))
    reason = (form.get("reason") or "brak").strip()
    notes = (form.get("notes") or "").strip()
    date_raw = (form.get("date") or "").strip()
    try:
        doc_date = datetime.strptime(date_raw, "%Y-%m-%d") if date_raw else datetime.now()
    except ValueError:
        doc_date = datetime.now()
    product_ids = form.getlist("product_id")
    quantities = form.getlist("quantity")
    prices = form.getlist("price")
    items = []
    for i, pid in enumerate(product_ids):
        if not pid:
            continue
        try:
            qty = float(quantities[i]); pr_ = float(prices[i])
        except (ValueError, IndexError):
            continue
        if qty > 0:
            items.append((int(pid), qty, pr_))
    if not items:
        return RedirectResponse(url="/purchase-returns/new?error=empty", status_code=303)
    prefix = f"PR-{doc_date.strftime('%Y%m%d')}-"
    last = db.query(PurchaseReturn).filter(PurchaseReturn.number.like(f"{prefix}%")).order_by(PurchaseReturn.number.desc()).first()
    seq = 0
    if last:
        try:
            seq = int(last.number.split("-")[-1])
        except (ValueError, IndexError):
            seq = 0
    number = f"{prefix}{str(seq + 1).zfill(4)}"
    total = sum(q * p for _, q, p in items)
    doc = PurchaseReturn(number=number, partner_id=partner_id, warehouse_id=warehouse_id,
                         date=doc_date, status="draft", reason=reason, total=total, notes=notes,
                         user_id=current_user.id if current_user else None)
    db.add(doc); db.flush()
    for pid, q, p in items:
        db.add(PurchaseReturnItem(return_id=doc.id, product_id=pid, quantity=q, price=p, total=q * p))
    db.commit()
    return RedirectResponse(url=f"/purchase-returns/{doc.id}", status_code=303)
```

- [ ] **Step 3: Detail + confirm + cancel**

```python
@router.get("/{doc_id}", response_class=HTMLResponse)
async def pr_detail(doc_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    if not _require_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    doc = db.query(PurchaseReturn).filter(PurchaseReturn.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/purchase-returns", status_code=303)
    return templates.TemplateResponse("purchase_returns/detail.html",
        {"request": request, "doc": doc, "current_user": current_user})

@router.post("/{doc_id}/confirm")
async def pr_confirm(doc_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    if not _require_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    doc = db.query(PurchaseReturn).filter(PurchaseReturn.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/purchase-returns", status_code=303)
    try:
        confirm_return(db, doc, current_user=current_user, client_host=request.client.host if request.client else None)
    except DocumentError as e:
        from urllib.parse import quote
        return RedirectResponse(url=f"/purchase-returns/{doc_id}?error={quote(str(e))}", status_code=303)
    return RedirectResponse(url=f"/purchase-returns/{doc_id}", status_code=303)

@router.post("/{doc_id}/cancel")
async def pr_cancel(doc_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(require_auth)):
    if not _require_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    doc = db.query(PurchaseReturn).filter(PurchaseReturn.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/purchase-returns", status_code=303)
    try:
        cancel_return(db, doc, current_user=current_user)
    except DocumentError as e:
        from urllib.parse import quote
        return RedirectResponse(url=f"/purchase-returns/{doc_id}?error={quote(str(e))}", status_code=303)
    return RedirectResponse(url=f"/purchase-returns/{doc_id}", status_code=303)
```

- [ ] **Step 4: Syntax check + commit**

Run: `python -c "import ast; ast.parse(open(r'app/routes/purchase_returns.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

```bash
git add app/routes/purchase_returns.py
git commit -m "feat(purchase-return): router (list/new/create/detail/confirm/cancel + price API)"
```

---

## Task 6: Templatelar

**Files:**
- Create: `app/templates/purchase_returns/{list,new,detail}.html`
- Reference: `app/templates/purchases/{list,new,edit}.html` (mavjud naqsh, `{% extends "base.html" %}`)

- [ ] **Step 1: `list.html`** — jadval (number, sana, yetkazib beruvchi, jami, status badge), "Yangi qaytarish" tugmasi. `purchases/list.html` ni shablon sifatida nusxalang, ustunlarni moslang. "Orqaga" tugmasi rol asosida ([[back-button-role]]).

- [ ] **Step 2: `new.html`** — forma: yetkazib beruvchi select, ombor select, sana, mahsulot qatorlari (JS: qator qo'shish; mahsulot tanlanganda `GET /purchase-returns/price?product_id=` orqali tannarx avtomatik to'ldiriladi, narx tahrirlanadi, qator jami hisoblanadi), sabab select (brak/expired/other), izoh. Submit `POST /purchase-returns`. CSRF token hidden input ([[common-pitfalls]] CSRF).

- [ ] **Step 3: `detail.html`** — hujjat boshi + qatorlar jadvali + jami. status `draft` bo'lsa "Tasdiqlash" tugmasi (`POST /{id}/confirm`); `confirmed` bo'lsa "Bekor qilish" (`POST /{id}/cancel`). `request.query_params.error` bo'lsa alert. CSRF token.

- [ ] **Step 4: Verify** — Jinja syntaxni `python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('purchase_returns/new.html')"` bilan tekshiring (yuklanadi).

- [ ] **Step 5: Commit**

```bash
git add app/templates/purchase_returns/
git commit -m "feat(purchase-return): list/new/detail templatelar"
```

---

## Task 7: Wiring + smoke + manual verifikatsiya

**Files:**
- Modify: `app/main.py` (router include + startup'da `ensure_purchase_return_tables`)
- Modify: `app/templates/base.html` (navbar havola)

- [ ] **Step 1: Router'ni ulash** (`main.py`, boshqa `include_router` lar yonida)

```python
from app.routes import purchase_returns
app.include_router(purchase_returns.router)
```

- [ ] **Step 2: Startup'da jadval yaratish** (`main.py` startup event'ida, boshqa `ensure_*` chaqiruvlar yonida; pending tranzaksiya orasida emas — [[schema-migration-pattern]])

```python
from app.utils.db_schema import ensure_purchase_return_tables
# startup ichida boshqa ensure_* lardan keyin:
ensure_purchase_return_tables(db)
```

- [ ] **Step 3: Navbar havola** (`base.html`, "Xaridlar" yoki "Asosiy modullar" yonida)

```html
<a class="nav-link" href="/purchase-returns"><i class="bi bi-arrow-return-left"></i> Qaytarishlar</a>
```

- [ ] **Step 4: To'liq test to'plami**

Run: `python -m pytest tests/test_purchase_return.py -v`
Expected: hammasi PASS

- [ ] **Step 5: Import smoke** (butun app yuklanadimi)

Run: `python -c "import app.main; print('APP OK')"`
Expected: APP OK

- [ ] **Step 6: Manual verifikatsiya (dev yoki tasdiqlangan deploy'dan keyin)**
  1. `/purchase-returns/new` ochiladi, forma ko'rinadi
  2. Yetkazib beruvchi + ombor + mahsulot (tannarx avtomatik) → qoralama saqlanadi
  3. Detail'da "Tasdiqlash" → stock kamayadi (Qoldiq hisobotida), yetkazib beruvchi balansi kamayadi
  4. Reconciliation hisobotida "Xarid qaytarish" DEBIT qatori ko'rinadi, closing to'g'ri
  5. "Bekor qilish" → stock va balans tiklanadi

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/templates/base.html
git commit -m "feat(purchase-return): router ulash + navbar + startup jadval"
```

---

## Self-Review natijasi (spec qamrovi)

| Spec talab | Task |
|---|---|
| Data model (2 jadval) | Task 1 |
| draft→confirm→cancel oqimi | Task 2, 3 |
| Atomik confirm (stock − + balans + + audit) | Task 2 |
| Sign konvensiya, purchase_price tegilmaydi | Task 2 (test) |
| Double-confirm himoyasi | Task 2 |
| Ombordan ko'p qaytarish rad | Task 2 |
| Bekor/revert | Task 3 |
| Reconciliation DEBIT integratsiya | Task 4 |
| UI (list/new/detail + price API) | Task 5, 6 |
| Rol (admin/manager), navbar, Orqaga | Task 5, 6, 7 |
| Startup jadval (ensure helper) | Task 7 |
| Test rejasi | Task 1-4, 7 |

**Deploy:** Tier B — backup, tungi oyna, smoke, restart (server2220'da `taskkill /PID` + `schtasks /run "TOTLI_BI_Server"`). Rollback: jadvallar additive, branch revert + restart.
