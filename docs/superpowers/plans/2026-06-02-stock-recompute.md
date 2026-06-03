# Stock Recompute Pattern — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `stocks.quantity` keshini movement ledger'iga sinxron tutib, kesh-desync drift'ini ildizdan yo'qotish (inkremental yozuv + risk-nuqtalarda reconcile + bitta-row guard + monitor).

**Architecture:** Yozuv yo'li O(1) inkremental (`create_stock_movement` o'zgarmaydi). `app/services/stock_service.py` ga `compute_stock_quantity` (kanonik = Σmovements) + `reconcile_stock` (set + dublikat merge + audit) qo'shiladi. Risk-operatsiyalar (transfer, QLD/INV) reconcile chaqiradi. Jonli DB'ga (wh,product) unique index ensure qilinadi (dublikat merge → index). Drift monitor kunlik.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2.0, SQLite, pytest (`tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-06-02-stock-recompute-design.md`
**Root cause:** memory `project_stock_drift_rootcause_20260602`

---

## Muhim faktlar (Faza 1'da tasdiqlangan)
- `Stock` modelida `UniqueConstraint("warehouse_id","product_id", name="uq_stock_wh_prod")` ALLAQACHON bor (database.py:412) → test DB'da dublikat imkonsiz. Jonli DB'da dublikat = ORM-DB drift (jadval konstraintsiz yaratilgan) → `ensure_stock_unique_index` bilan hal qilinadi.
- `StockMovement`: warehouse_id, product_id, quantity_change, quantity_after, operation_type, document_type, document_id, created_at.
- `create_stock_movement` (stock_service.py:49) har doim `stock.quantity += quantity_change` (O(1)) — O'ZGARMAYDI.
- ⚠️ InitialBalance movement'siz stock'lar bor edi ([[stock-drift-reconciliation]]) → reconcile `move_count>0` guard bilan ularni 0 qilmaydi.
- conftest: `db` (in-memory, UniqueConstraint amal qiladi), `sample_warehouse`, `sample_product`, `sample_stock` (100 qty, movement'siz).

## Fayl tuzilishi
| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/services/stock_service.py` | compute_stock_quantity + reconcile_stock | Modify |
| `app/models/database.py` | ensure_stock_unique_index() | Modify |
| `app/routes/warehouse.py` | transfer confirm/revert/delete → reconcile | Modify |
| `app/routes/qoldiqlar.py` | QLD/INV confirm/revert → reconcile | Modify |
| `scripts/backfill_stock_quantities.py` | data fix (dry-run/apply, 10 mahsulot) | YANGI |
| `scripts/stock_drift_monitor.py` | kunlik monitor + Telegram | YANGI |
| `tests/test_stock_reconcile.py` | unit + bug-repro | YANGI |

---

## Task 1: `compute_stock_quantity` — kanonik formula

**Files:**
- Modify: `app/services/stock_service.py`
- Test: `tests/test_stock_reconcile.py` (YANGI)

- [ ] **Step 1: Failing test yoz**

`tests/test_stock_reconcile.py`:
```python
from datetime import datetime
from app.models.database import Stock, StockMovement, Warehouse, Product, Unit
from app.services.stock_service import compute_stock_quantity


def _wh(db, wid=1):
    w = Warehouse(id=wid, name=f"WH{wid}", code=f"W{wid}")
    db.add(w); db.commit(); return w


def _prod(db, pid=1):
    u = Unit(name="kg"); db.add(u); db.flush()
    p = Product(id=pid, name=f"P{pid}", unit_id=u.id, is_active=True)
    db.add(p); db.commit(); return p


def _mv(db, wid, pid, change, op="adjustment"):
    db.add(StockMovement(warehouse_id=wid, product_id=pid, quantity_change=change,
                         quantity_after=0, operation_type=op, document_type="X",
                         document_id=1, created_at=datetime(2026, 6, 1)))
    db.commit()


def test_compute_empty_is_zero(db):
    _wh(db); _prod(db)
    assert compute_stock_quantity(db, 1, 1) == 0.0


def test_compute_sums_movements(db):
    _wh(db); _prod(db)
    _mv(db, 1, 1, +235.65)
    _mv(db, 1, 1, -32.5)
    _mv(db, 1, 1, -32.5)
    assert abs(compute_stock_quantity(db, 1, 1) - 170.65) < 1e-9


def test_compute_isolated_per_wh_product(db):
    _wh(db, 1); _wh(db, 2); _prod(db, 1); _prod(db, 2)
    _mv(db, 1, 1, +10)
    _mv(db, 2, 1, +99)
    _mv(db, 1, 2, +5)
    assert compute_stock_quantity(db, 1, 1) == 10.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `python -m pytest tests/test_stock_reconcile.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_stock_quantity'`

- [ ] **Step 3: Implementatsiya** — `app/services/stock_service.py` ga qo'sh (faylda `from sqlalchemy import func` borligini tekshir, yo'q bo'lsa qo'sh):
```python
def compute_stock_quantity(db: Session, warehouse_id: int, product_id: int) -> float:
    """Kanonik qoldiq = shu (wh, product) uchun barcha movement quantity_change yig'indisi."""
    return float(
        db.query(func.coalesce(func.sum(StockMovement.quantity_change), 0.0))
        .filter(
            StockMovement.warehouse_id == warehouse_id,
            StockMovement.product_id == product_id,
        )
        .scalar() or 0.0
    )
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `python -m pytest tests/test_stock_reconcile.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**
```bash
git add app/services/stock_service.py tests/test_stock_reconcile.py
git commit -m "feat(stock): compute_stock_quantity kanonik formula + testlar"
```

---

## Task 2: `reconcile_stock` — set + dublikat merge + audit + initial guard

**Files:**
- Modify: `app/services/stock_service.py`
- Test: `tests/test_stock_reconcile.py`

- [ ] **Step 1: Failing test yoz** (faylga qo'sh)
```python
from app.models.database import AuditLog
from app.services.stock_service import reconcile_stock


def test_reconcile_sets_stored_to_ledger(db):
    _wh(db); _prod(db)
    s = Stock(warehouse_id=1, product_id=1, quantity=999)  # noto'g'ri stored
    db.add(s); db.commit()
    _mv(db, 1, 1, +100)
    _mv(db, 1, 1, -30)
    old, new = reconcile_stock(db, 1, 1, reason="test"); db.commit()
    assert old == 999.0
    assert new == 70.0
    db.refresh(s); assert s.quantity == 70.0


def test_reconcile_writes_audit(db):
    _wh(db); _prod(db)
    db.add(Stock(warehouse_id=1, product_id=1, quantity=0)); db.commit()
    _mv(db, 1, 1, +50)
    reconcile_stock(db, 1, 1, reason="transfer_confirm", actor="admin"); db.commit()
    logs = db.query(AuditLog).filter(AuditLog.entity_type == "stock").all()
    assert len(logs) == 1
    assert "transfer_confirm" in (logs[0].details or "")


def test_reconcile_no_movements_is_noop(db):
    """move_count=0 (faqat initial balance) bo'lsa stored TEGILMAYDI (0 qilib yubormaydi)."""
    _wh(db); _prod(db)
    s = Stock(warehouse_id=1, product_id=1, quantity=100)  # initial, movement yo'q
    db.add(s); db.commit()
    old, new = reconcile_stock(db, 1, 1, reason="test"); db.commit()
    assert old == 100.0 and new == 100.0
    db.refresh(s); assert s.quantity == 100.0


def test_reconcile_idempotent(db):
    _wh(db); _prod(db)
    db.add(Stock(warehouse_id=1, product_id=1, quantity=0)); db.commit()
    _mv(db, 1, 1, +42)
    reconcile_stock(db, 1, 1, reason="x"); db.commit()
    old, new = reconcile_stock(db, 1, 1, reason="x"); db.commit()
    assert old == new == 42.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `python -m pytest tests/test_stock_reconcile.py -k reconcile -v`
Expected: FAIL — `ImportError: cannot import name 'reconcile_stock'`

- [ ] **Step 3: Implementatsiya** — `app/services/stock_service.py` ga qo'sh (`AuditLog` importini ta'minla):
```python
def _stock_movement_count(db: Session, warehouse_id: int, product_id: int) -> int:
    return db.query(StockMovement).filter(
        StockMovement.warehouse_id == warehouse_id,
        StockMovement.product_id == product_id,
    ).count()


def reconcile_stock(db: Session, warehouse_id: int, product_id: int, *,
                    reason: str, actor: str = None) -> tuple:
    """stocks.quantity = compute_stock_quantity (kanonik). Dublikat row'larni 1 ga
    birlashtiradi. move_count=0 (faqat initial) bo'lsa TEGMAYDI. commit qilmaydi.
    Qaytaradi: (old, new).
    """
    rows = db.query(Stock).filter(
        Stock.warehouse_id == warehouse_id,
        Stock.product_id == product_id,
    ).all()
    # Dublikat merge (jonli DB drift safety-net)
    if len(rows) > 1:
        total = sum(float(r.quantity or 0) for r in rows)
        keep = rows[0]; keep.quantity = total
        old_ids = [r.id for r in rows[1:]]
        if old_ids:
            db.query(StockMovement).filter(StockMovement.stock_id.in_(old_ids)).update(
                {StockMovement.stock_id: keep.id}, synchronize_session=False)
        for r in rows[1:]:
            db.delete(r)
        db.flush()
        stock = keep
    elif len(rows) == 1:
        stock = rows[0]
    else:
        stock = None

    old = float(stock.quantity or 0) if stock else 0.0

    # Initial-balance guard: movement umuman yo'q bo'lsa rebuild qilmaymiz
    if _stock_movement_count(db, warehouse_id, product_id) == 0:
        return (old, old)

    new = compute_stock_quantity(db, warehouse_id, product_id)
    if stock is None:
        stock = Stock(warehouse_id=warehouse_id, product_id=product_id, quantity=new)
        db.add(stock); db.flush()
    else:
        stock.quantity = new
    db.add(AuditLog(
        user_name=actor or "system",
        action="reconcile",
        entity_type="stock",
        entity_id=product_id,
        entity_number=f"wh{warehouse_id}/p{product_id}",
        details=f"reason={reason}; {old:.3f} -> {new:.3f}; delta={new - old:+.3f}",
    ))
    return (old, new)
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `python -m pytest tests/test_stock_reconcile.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**
```bash
git add app/services/stock_service.py tests/test_stock_reconcile.py
git commit -m "feat(stock): reconcile_stock (set + merge + audit + initial guard)"
```

---

## Task 3: 🎯 Bug reproduksiyasi testi (transfer churn + back-date)

**Files:**
- Test: `tests/test_stock_reconcile.py`

- [ ] **Step 1: Bug-repro test yoz** (faylga qo'sh) — aynan Faza 1 stsenariysi

```python
def test_reconcile_fixes_transfer_churn_drift(db):
    """QLD adjustment + transfer churn → stored noto'g'ri bo'lsa ham reconcile ledger'ga tushiradi."""
    _wh(db, 2); _prod(db, 249)
    # Movement ledger: QLD +235.65, transfer churn (net), OT-0002/0004 out, production
    for ch in [235.65, -32.5, +32.5, -32.5, +32.5, -32.5, -32.5, -2.5, -20, -10, +66.96, -3.7, -5.35, -6.56]:
        _mv(db, 2, 249, ch, op="adjustment")
    # Stored noto'g'ri (drift simulatsiyasi)
    s = Stock(warehouse_id=2, product_id=249, quantity=254.50)
    db.add(s); db.commit()
    old, new = reconcile_stock(db, 2, 249, reason="data_fix"); db.commit()
    assert abs(old - 254.50) < 0.01
    assert abs(new - 189.50) < 0.01   # ledger = jismoniy haqiqat
    db.refresh(s); assert abs(s.quantity - 189.50) < 0.01
```

- [ ] **Step 2: Test o'tishini tasdiqla** (reconcile allaqachon ishlaydi)

Run: `python -m pytest tests/test_stock_reconcile.py::test_reconcile_fixes_transfer_churn_drift -v`
Expected: PASS

- [ ] **Step 3: Commit**
```bash
git add tests/test_stock_reconcile.py
git commit -m "test(stock): transfer churn drift bug reproduksiyasi"
```

---

## Task 4: `ensure_stock_unique_index` — jonli DB dublikat merge + unique index

**Files:**
- Modify: `app/models/database.py`

- [ ] **Step 1: Funksiya yoz** — mavjud `ensure_*` pattern bo'yicha (database.py'da boshqa ensure_* funksiyalar yonida):
```python
def ensure_stock_unique_index():
    """Jonli DB'da (warehouse_id, product_id) bo'yicha dublikat Stock row'larni birlashtirib,
    unique index yaratadi (ORM'da UniqueConstraint bor, lekin eski jadval konstraintsiz yaratilgan bo'lishi mumkin).
    Idempotent."""
    from sqlalchemy import text
    with engine.begin() as conn:
        # 1) Dublikatlarni topish
        dups = conn.execute(text(
            "SELECT warehouse_id, product_id, COUNT(*) c FROM stocks "
            "GROUP BY warehouse_id, product_id HAVING c > 1"
        )).fetchall()
        for wh, pid, _c in dups:
            ids = [r[0] for r in conn.execute(text(
                "SELECT id FROM stocks WHERE warehouse_id=:w AND product_id=:p ORDER BY id"),
                {"w": wh, "p": pid}).fetchall()]
            keep, drop = ids[0], ids[1:]
            total = conn.execute(text(
                "SELECT COALESCE(SUM(quantity),0) FROM stocks WHERE warehouse_id=:w AND product_id=:p"),
                {"w": wh, "p": pid}).scalar()
            conn.execute(text("UPDATE stocks SET quantity=:q WHERE id=:id"), {"q": total, "id": keep})
            if drop:
                conn.execute(text(f"UPDATE stock_movements SET stock_id=:k WHERE stock_id IN ({','.join(map(str,drop))})"), {"k": keep})
                conn.execute(text(f"DELETE FROM stocks WHERE id IN ({','.join(map(str,drop))})"))
            print(f"stock dublikat birlashtirildi: wh={wh} pid={pid} -> id={keep} total={total}")
        # 2) Unique index
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_wh_prod_idx ON stocks(warehouse_id, product_id)"
        ))
        print("stocks(warehouse_id, product_id) unique index ta'minlandi.")
```

- [ ] **Step 2: Startup'ga ulash** — `init_db` (yoki ensure_* lar chaqiriladigan joy) ga `ensure_stock_unique_index()` qo'sh. Mavjud `ensure_currency_columns()` va boshqalar chaqirilgan joyni top (database.py ichida 2057 atrofida) va yoniga qo'sh.

- [ ] **Step 3: Sintaksis tekshiruvi**

Run: `python -c "import ast; ast.parse(open(r'app/models/database.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Import tekshiruvi (circular yo'qligi)**

Run: `python -c "import os; os.environ['SECRET_KEY']='x'; import app.models.database; print('import OK')"`
Expected: import OK

- [ ] **Step 5: Commit**
```bash
git add app/models/database.py
git commit -m "feat(stock): ensure_stock_unique_index (dublikat merge + unique index)"
```

---

## Task 5: Reconcile chaqiruvlari — `warehouse.py` (transfer confirm/revert/delete)

**Files:**
- Modify: `app/routes/warehouse.py` (confirm:623-695, revert:709-751, delete:760+)

- [ ] **Step 1: confirm migratsiya** — `warehouse_transfer_confirm` ichida, create_stock_movement loop'idan SO'NG, `db.commit()` (695) dan OLDIN:
```python
    from app.services.stock_service import reconcile_stock
    db.flush()
    affected = {(transfer.from_warehouse_id, item.product_id) for item in items} | \
               {(transfer.to_warehouse_id, item.product_id) for item in items}
    for wh, pid in affected:
        reconcile_stock(db, wh, pid, reason="transfer_confirm",
                        actor=current_user.username if current_user else None)
```

- [ ] **Step 2: revert migratsiya** — `warehouse_transfer_revert` ichida, loop'dan so'ng, `db.commit()` (751) dan oldin (xuddi shu pattern, reason="transfer_revert").

- [ ] **Step 3: delete migratsiya** — `warehouse_transfer_delete` (760) ni o'qib, movement o'chirilgandan so'ng (delete_stock_movements_for_document chaqirilsa) ta'sirlangan (wh,pid) uchun reconcile(reason="transfer_delete"). Agar delete movement o'chirmasa — reconcile baribir to'g'ri (Σmovements).

- [ ] **Step 4: Sintaksis + mavjud testlar**

Run: `python -c "import ast; ast.parse(open(r'app/routes/warehouse.py', encoding='utf-8').read()); print('OK')"`
Run: `python -m pytest tests/ -q`
Expected: OK; mavjud testlar baseline'dan oshmaydi (4 pre-existing fail)

- [ ] **Step 5: Commit**
```bash
git add app/routes/warehouse.py
git commit -m "feat(stock): transfer confirm/revert/delete -> reconcile_stock"
```

---

## Task 6: Reconcile chaqiruvlari — `qoldiqlar.py` (QLD/INV confirm/revert)

**Files:**
- Modify: `app/routes/qoldiqlar.py` (QLD confirm loop:1759-1789, va tegishli revert)

- [ ] **Step 1: confirm migratsiya** — QLD/INV tasdiqlash funksiyasida, item loop'idan SO'NG (1789), `db.commit()` (1798) dan OLDIN:
```python
    from app.services.stock_service import reconcile_stock
    db.flush()
    for wh, pid in {(it.warehouse_id, it.product_id) for it in doc.items}:
        reconcile_stock(db, wh, pid, reason="stock_adjustment_confirm",
                        actor=current_user.username if current_user else None)
```

- [ ] **Step 2: revert migratsiya** — QLD/INV tasdiq bekor qilish funksiyasini topib (stock movementlar o'chirilgach/teskari qilingach), ta'sirlangan (wh,pid) uchun reconcile(reason="stock_adjustment_revert"). Funksiyani `Select-String -Path app/routes/qoldiqlar.py -Pattern "StockAdjustmentDoc"` bilan top.

- [ ] **Step 3: Sintaksis + testlar**

Run: `python -c "import ast; ast.parse(open(r'app/routes/qoldiqlar.py', encoding='utf-8').read()); print('OK')"`
Run: `python -m pytest tests/ -q`
Expected: OK; baseline'dan oshmaydi

- [ ] **Step 4: Commit**
```bash
git add app/routes/qoldiqlar.py
git commit -m "feat(stock): QLD/INV confirm/revert -> reconcile_stock"
```

---

## Task 7: Data fix skript — `backfill_stock_quantities.py`

**Files:**
- Create: `scripts/backfill_stock_quantities.py`

- [ ] **Step 1: Skript yoz** (dry-run default, --apply bilan yozadi)
```python
"""Driftli stock'larni ledger'dan qayta quradi (compute_stock_quantity).
Default DRY-RUN. --apply bilan yozadi (backup oling!). move_count=0 (initial) tegilmaydi.

    python scripts/backfill_stock_quantities.py            # hisobot
    python scripts/backfill_stock_quantities.py --apply    # yozish
"""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")

from app.models.database import SessionLocal, Stock, Warehouse, Product
from app.services.stock_service import compute_stock_quantity, reconcile_stock

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    try:
        wh = {w.id: w.name for w in db.query(Warehouse).all()}
        pn = {p.id: p.name for p in db.query(Product).all()}
        changes = []
        for s in db.query(Stock).all():
            stored = float(s.quantity or 0)
            computed = compute_stock_quantity(db, s.warehouse_id, s.product_id)
            # initial guard: movement yo'q bo'lsa o'tkazib yuborish
            from app.models.database import StockMovement
            mc = db.query(StockMovement).filter(
                StockMovement.warehouse_id == s.warehouse_id,
                StockMovement.product_id == s.product_id).count()
            if mc == 0:
                continue
            if abs(stored - computed) > 0.001:
                changes.append((s.warehouse_id, s.product_id, stored, computed, computed - stored))
        changes.sort(key=lambda x: abs(x[4]), reverse=True)
        print("=" * 90)
        print(f"STOCK BACKFILL — {'APPLY' if APPLY else 'DRY-RUN'}  | driftli: {len(changes)}")
        print("=" * 90)
        print(f"{'ombor':<22}{'mahsulot':<28}{'stored':>11}{'computed':>11}{'delta':>10}")
        for w, p, st, co, d in changes:
            print(f"  {wh.get(w,'?')[:20]:<22}{pn.get(p,'?')[:26]:<28}{st:>11.2f}{co:>11.2f}{d:>+10.2f}")
        if APPLY:
            for w, p, *_ in changes:
                reconcile_stock(db, w, p, reason="backfill_recompute")
            db.commit()
            print(f"\n[APPLIED] {len(changes)} stock tuzatildi.")
        else:
            print("\n[DRY-RUN] Hech narsa yozilmadi. --apply uchun backup oling.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run (live DB, read-only)**

Run (PowerShell): `python scripts/backfill_stock_quantities.py`
Expected: ~10 driftli mahsulot ko'rinadi (HOLVA LIST'lar + etiketka/idish). Hech narsa yozilmaydi.

- [ ] **Step 3: Commit**
```bash
git add scripts/backfill_stock_quantities.py
git commit -m "feat(stock): backfill skript (dry-run/apply)"
```

---

## Task 8: Drift monitor — `stock_drift_monitor.py`

**Files:**
- Create: `scripts/stock_drift_monitor.py`

- [ ] **Step 1: Skript yoz**
```python
"""Kunlik stock drift monitor: stored vs Σmovements. Drift bo'lsa Telegram (Yordamchim) ga.
Task Scheduler bilan kunlik yuriladi."""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")

from app.models.database import SessionLocal, Stock, StockMovement, Warehouse, Product
from app.services.stock_service import compute_stock_quantity

THRESHOLD = 0.01


def main():
    db = SessionLocal()
    try:
        wh = {w.id: w.name for w in db.query(Warehouse).all()}
        pn = {p.id: p.name for p in db.query(Product).all()}
        drift = []
        for s in db.query(Stock).all():
            mc = db.query(StockMovement).filter(
                StockMovement.warehouse_id == s.warehouse_id,
                StockMovement.product_id == s.product_id).count()
            if mc == 0:
                continue
            stored = float(s.quantity or 0)
            computed = compute_stock_quantity(db, s.warehouse_id, s.product_id)
            if abs(stored - computed) > THRESHOLD:
                drift.append((wh.get(s.warehouse_id, '?'), pn.get(s.product_id, '?'), stored, computed, computed - stored))
        if not drift:
            print("Stock drift YO'Q.")
            return
        lines = [f"⚠️ Stock drift: {len(drift)} ta"]
        for w, p, st, co, d in sorted(drift, key=lambda x: abs(x[4]), reverse=True)[:15]:
            lines.append(f"{w[:14]} {p[:18]}: {st:.1f} vs {co:.1f} ({d:+.1f})")
        msg = "\n".join(lines)
        print(msg)
        try:
            from app.bot.services.notifier import notify_owner  # mavjud helper
            notify_owner(msg)
        except Exception as e:
            print(f"(Telegram yuborilmadi: {e})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```
(Eslatma: `notify_owner` mavjud emasligi mumkin — `app/bot/services/notifier.py` ni tekshirib to'g'ri owner-DM helper nomini ishlat; [[feedback-telegram-channel]] CLAUDE_BOT_TOKEN/Yordamchim.)

- [ ] **Step 2: Test run (live, read-only)**

Run: `python scripts/stock_drift_monitor.py`
Expected: hozir ~10 drift ko'rsatadi (backfill'dan oldin)

- [ ] **Step 3: Commit**
```bash
git add scripts/stock_drift_monitor.py
git commit -m "feat(stock): drift monitor (kunlik + Telegram)"
```

---

## Task 9: To'liq test + smoke

- [ ] **Step 1:** `python -m pytest tests/ -q` → faqat 4 baseline fail, qolgani yashil
- [ ] **Step 2:** `python -m pytest tests/test_endpoints_smoke.py tests/test_smoke.py -v` → yashil
- [ ] **Step 3:** har o'zgargan fayl AST tekshiruvi → OK

---

## Task 10: Deploy (tungi oyna, controller + foydalanuvchi)

> Subagent EMAS. Controller bajaradi.

- [ ] **Step 1: Backup** — `python -c "import sqlite3; s=sqlite3.connect(r'\\server2220\d\TOTLI BI\totli_holva.db'); d=sqlite3.connect(r'\\server2220\d\TOTLI BI\totli_holva.db.bak_pre_stock_recompute_20260602'); s.backup(d); d.close(); s.close()"`
- [ ] **Step 2:** `merge_duplicate_stocks` ensure (server restart ensure_stock_unique_index ni ishga tushiradi) yoki backfill dry-run ko'rsat → tasdiq
- [ ] **Step 3:** Backfill apply — `python scripts/backfill_stock_quantities.py --apply`
- [ ] **Step 4:** Server restart (DCOM kill 8080 PID + `schtasks /run /S server2220 /TN "TOTLI_BI_Server"`) → ensure_stock_unique_index ishga tushadi
- [ ] **Step 5:** Post-smoke — server UP (HTTP 200) + `python scripts/stock_drift_monitor.py` → "drift YO'Q"
- [ ] **Step 6:** Monitor Task Scheduler'ga (kunlik) — RDP'da
- [ ] **Step 7:** Rollback rejasi — backup tikla + git revert

---

## Self-Review natijasi (reja muallifi)
**Spec coverage:** compute (T1), reconcile+merge+guard (T2), bug-repro (T3), unique index (T4), reconcile call-sites transfer (T5) + QLD/INV (T6), data fix 10 (T7), monitor (T8), test (T9), rollout (T10) — barcha spec bo'limlari qoplangan. ✅
**Placeholder scan:** call-site task'lari aniq file:line + kod; "edge case" mavhumligi yo'q. T6 revert funksiya nomini grep bilan topish ko'rsatilgan (aniq). ✅
**Type consistency:** `compute_stock_quantity(db, wh, pid)->float`, `reconcile_stock(db, wh, pid, *, reason, actor=None)->(old,new)`, `_stock_movement_count` — izchil. ✅
