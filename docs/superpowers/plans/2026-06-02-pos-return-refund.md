# POS Qaytarish Refund (Sub-1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** POS qaytarish (return_sale) tasdiqlanganda naqd sotuv uchun kassadan proporsional refund (chiqim) yaratish, revert'da qaytarish, Z-hisobot va partner balansni to'g'rilash.

**Architecture:** Yangi `refund_service.compute_return_refund` (sof funksiya) original sotuvning naqd to'lovi va chegirmasiga qarab refund summasini hisoblaydi. `sales.py` return yaratish (3933) refund expense Payment yaratadi; revert (4018) uni o'chiradi. `z_cash_summary` refundni naqd chiqim sanaydi.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2.0, SQLite, pytest (`tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-06-02-pos-return-refund-design.md`
**Root cause:** memory `project_return_refund_bug_20260602`

---

## Muhim faktlar (verified)
- Return yaratish: `sales.py:~3933` — `sale` (original Order) va `sale_items_by_product` (dict pid→OrderItem) scope'da; `return_order` yaratiladi, `total_return` item narxlaridan; `return_order.total/paid = total_return`. `current_user` bor.
- Return revert: `sales.py:~4018` `sales_return_revert(return_order_id)` — `doc` (return_sale), stock −qty revert, `doc.status="cancelled"`.
- `Payment` fields: number, date, type ('income'/'expense'), cash_register_id, partner_id, order_id, amount, payment_type ('cash'/'naqd'/...), category, status, user_id.
- `Order`: id, number, type, status, partner_id, total, subtotal, paid, debt. `.items` → OrderItem (product_id, quantity, price, total).
- `sync_cash_balance`: `from app.services.finance_service import sync_cash_balance`.
- `recompute_partner_balance`: `from app.services.partner_balance_service import recompute_partner_balance` (DEPLOYED).
- PAY raqami pattern (sales.py'da mavjud): `pay_number = f"PAY-{datetime.now().strftime('%Y%m%d')}-{seq:04d}"`.
- conftest: `db`, `sample_partner`, `sample_cash` (CashRegister), `sample_product`.

## Fayl tuzilishi
| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/services/refund_service.py` | compute_return_refund | YANGI |
| `app/routes/sales.py` | return yaratish + revert refund | Modify |
| `app/utils/z_cash_summary.py` | sale_return naqd chiqim | Modify |
| `scripts/backfill_return_refunds.py` | data fix | YANGI |
| `tests/test_return_refund.py` | unit + integ | YANGI |

---

## Task 1: `compute_return_refund` — refund hisoblash

**Files:**
- Create: `app/services/refund_service.py`
- Test: `tests/test_return_refund.py` (YANGI)

- [ ] **Step 1: Failing test yoz**

`tests/test_return_refund.py`:
```python
from datetime import datetime
from app.models.database import Order, OrderItem, Payment, Partner, CashRegister, Product, Unit
from app.services.refund_service import compute_return_refund


def _setup_sale(db, *, items, total, subtotal, cash_amount, cash_register_id=1, paid=None):
    u = Unit(name="kg"); db.add(u); db.flush()
    p = Partner(name="Mijoz", phone="+1", balance=0, is_active=True); db.add(p); db.flush()
    cr = CashRegister(id=cash_register_id, name="Naqd", payment_type="naqd", is_active=True, opening_balance=0)
    db.add(cr); db.flush()
    sale = Order(number="S-1", type="sale", status="completed", partner_id=p.id,
                 total=total, subtotal=subtotal, paid=paid if paid is not None else total, debt=0,
                 date=datetime(2026, 6, 2))
    db.add(sale); db.flush()
    for pid, qty, price in items:
        pr = db.query(Product).filter(Product.id == pid).first()
        if not pr:
            pr = Product(id=pid, name=f"P{pid}", unit_id=u.id, is_active=True); db.add(pr); db.flush()
        db.add(OrderItem(order_id=sale.id, product_id=pid, quantity=qty, price=price, total=qty*price))
    if cash_amount > 0:
        db.add(Payment(number="PAY-1", type="income", payment_type="cash", status="confirmed",
                       order_id=sale.id, partner_id=p.id, cash_register_id=cash_register_id,
                       amount=cash_amount, date=datetime(2026, 6, 2)))
    db.commit(); db.refresh(sale)
    return sale


def test_full_cash_return_refunds_paid(db):
    # 520k items, 500k total (20k chegirma), 500k naqd
    sale = _setup_sale(db, items=[(1, 3, 170000), (2, 1, 10000)], total=500000, subtotal=520000, cash_amount=500000)
    r = compute_return_refund(db, sale, [(1, 3), (2, 1)])
    assert r["ratio"] == 1.0
    assert r["refund_cash"] == 500000.0      # paid, 520k EMAS
    assert r["return_total"] == 500000.0     # chegirmali
    assert r["refund_cash_register_id"] == 1


def test_partial_cash_return_proportional(db):
    sale = _setup_sale(db, items=[(1, 4, 100000)], total=400000, subtotal=400000, cash_amount=400000)
    r = compute_return_refund(db, sale, [(1, 1)])   # 1/4 qaytdi
    assert r["ratio"] == 0.25
    assert r["refund_cash"] == 100000.0
    assert r["return_total"] == 100000.0


def test_debt_sale_no_cash_refund(db):
    # qarzga sotuv: naqd to'lov yo'q
    sale = _setup_sale(db, items=[(1, 2, 100000)], total=200000, subtotal=200000, cash_amount=0, paid=0)
    r = compute_return_refund(db, sale, [(1, 2)])
    assert r["refund_cash"] == 0.0
    assert r["return_total"] == 200000.0
    assert r["refund_cash_register_id"] is None


def test_zero_subtotal_safe(db):
    sale = _setup_sale(db, items=[(1, 1, 0)], total=0, subtotal=0, cash_amount=0, paid=0)
    r = compute_return_refund(db, sale, [(1, 1)])
    assert r["ratio"] == 0.0
    assert r["refund_cash"] == 0.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `python -m pytest tests/test_return_refund.py -v`
Expected: FAIL — ModuleNotFoundError refund_service

- [ ] **Step 3: Implementatsiya**

`app/services/refund_service.py`:
```python
"""Qaytarish refund hisoblash — original sotuvning naqd to'lovi va chegirmasiga qarab."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import Payment


def compute_return_refund(db: Session, sale, returned_lines) -> dict:
    """returned_lines: [(product_id, qty), ...]. Qaytaradi:
    {refund_cash, return_total, refund_cash_register_id, ratio}.
    refund_cash = sotuvning NAQD to'lovi × proporsiya (chegirma avtomatik).
    return_total = sale.total × proporsiya (chegirmali).
    """
    sale_items = {it.product_id: it for it in (sale.items or [])}
    returned_value = 0.0
    for pid, qty in returned_lines:
        it = sale_items.get(pid)
        if it and float(qty or 0) > 0:
            returned_value += float(qty) * float(it.price or 0)
    subtotal = float(sale.subtotal or 0) or float(sale.total or 0)
    ratio = (returned_value / subtotal) if subtotal > 0 else 0.0
    if ratio > 1.0:
        ratio = 1.0
    cash_pays = db.query(Payment).filter(
        Payment.order_id == sale.id,
        Payment.type == "income",
        Payment.payment_type.in_(["cash", "naqd"]),
        or_(Payment.status == "confirmed", Payment.status.is_(None)),
    ).all()
    cash_paid = sum(float(p.amount or 0) for p in cash_pays)
    refund_cash = round(cash_paid * ratio, 2)
    return_total = round(float(sale.total or 0) * ratio, 2)
    refund_cash_register_id = None
    if cash_pays:
        refund_cash_register_id = max(cash_pays, key=lambda p: float(p.amount or 0)).cash_register_id
    return {
        "refund_cash": refund_cash,
        "return_total": return_total,
        "refund_cash_register_id": refund_cash_register_id,
        "ratio": ratio,
    }
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `python -m pytest tests/test_return_refund.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**
```bash
git add app/services/refund_service.py tests/test_return_refund.py
git commit -m "feat(refund): compute_return_refund (proporsional, chegirma, naqd/qarz)"
```

---

## Task 2: Return yaratish — refund Payment + chegirmali total (`sales.py:3933`)

**Files:**
- Modify: `app/routes/sales.py` (return creation ~3933-3984)

- [ ] **Step 1: Region o'qish** — `sales.py` 3900-3990 ni o'qib, `sale`, `sale_items_by_product`, `product_ids`, `quantities`, `return_order`, `total_return` o'zgaruvchilarini tasdiqla.

- [ ] **Step 2: Migratsiya** — `return_order.total/paid` o'rnatilgan joydan keyin (~3972-3976), `db.commit()` dan oldin, refund mantiqi qo'sh:
```python
    # === Refund: original sotuv naqd to'langan bo'lsa kassadan proporsional chiqim ===
    from app.services.refund_service import compute_return_refund
    returned_lines = [(product_ids[i], quantities[i]) for i in range(min(len(product_ids), len(quantities)))
                      if product_ids[i] and quantities[i] > 0]
    rinfo = compute_return_refund(db, sale, returned_lines)
    # return total — chegirmali qiymatga moslash (item narxi emas) -> partner balans toza
    if rinfo["return_total"] > 0:
        return_order.total = rinfo["return_total"]
        return_order.subtotal = rinfo["return_total"]
        return_order.paid = rinfo["return_total"]
    # Exchange guard: child sale bor bo'lsa refund yo'q
    has_child = db.query(Order.id).filter(Order.parent_order_id == return_order.id).first()
    if rinfo["refund_cash"] > 0 and rinfo["refund_cash_register_id"] and not has_child:
        _today = datetime.now().strftime('%Y%m%d')
        _last = db.query(Payment).filter(Payment.number.like(f"PAY-{_today}-%")).order_by(Payment.number.desc()).first()
        _seq = (int(_last.number.split("-")[-1]) + 1) if (_last and _last.number) else 1
        db.add(Payment(
            number=f"PAY-{_today}-{_seq:04d}",
            date=datetime.now(),
            type="expense",
            category="sale_return",
            payment_type="cash",
            status="confirmed",
            partner_id=sale.partner_id,
            order_id=return_order.id,
            cash_register_id=rinfo["refund_cash_register_id"],
            amount=rinfo["refund_cash"],
            description=f"Qaytarish refund: {return_order.number} ({sale.number})",
            user_id=current_user.id if current_user else None,
        ))
        db.flush()
        from app.services.finance_service import sync_cash_balance
        sync_cash_balance(db, rinfo["refund_cash_register_id"])
        if sale.partner_id:
            from app.services.partner_balance_service import recompute_partner_balance
            recompute_partner_balance(db, sale.partner_id, reason="sale_return_refund", ref=return_order.number)
    db.commit()
```
(Eslatma: agar joyda allaqachon `db.commit()` bor bo'lsa — refund blokini o'sha commitдан OLDIN qo'y, ikkilanmasin. `Order`, `Payment`, `datetime` import borligini tekshir.)

- [ ] **Step 3: Sintaksis + testlar**

Run: `python -c "import ast; ast.parse(open(r'app/routes/sales.py', encoding='utf-8').read()); print('OK')"`
Run: `python -m pytest tests/ -q`
Expected: OK; baseline 4 fail'dan oshmaydi

- [ ] **Step 4: Commit**
```bash
git add app/routes/sales.py
git commit -m "feat(refund): POS qaytarishda naqd refund + chegirmali total"
```

---

## Task 3: Return revert — refund Payment o'chirish (`sales.py:4018`)

**Files:**
- Modify: `app/routes/sales.py` (`sales_return_revert` ~4018-4058)

- [ ] **Step 1: Migratsiya** — `doc.status = "cancelled"` dan OLDIN (stock revert loop'idan keyin):
```python
    # Refund Payment'ni o'chirish (kassa naqdini qaytarish)
    refund_pays = db.query(Payment).filter(
        Payment.order_id == doc.id, Payment.category == "sale_return", Payment.type == "expense"
    ).all()
    _registers = set()
    for rp in refund_pays:
        if rp.cash_register_id:
            _registers.add(rp.cash_register_id)
        db.delete(rp)
    db.flush()
    from app.services.finance_service import sync_cash_balance
    for _cr in _registers:
        sync_cash_balance(db, _cr)
    if doc.partner_id:
        from app.services.partner_balance_service import recompute_partner_balance
        recompute_partner_balance(db, doc.partner_id, reason="sale_return_revert", ref=doc.number)
```

- [ ] **Step 2: Sintaksis + testlar**

Run: `python -c "import ast; ast.parse(open(r'app/routes/sales.py', encoding='utf-8').read()); print('OK')"`
Run: `python -m pytest tests/ -q`
Expected: OK; baseline'dan oshmaydi

- [ ] **Step 3: Commit**
```bash
git add app/routes/sales.py
git commit -m "feat(refund): qaytarish revert refund Payment'ni o'chiradi + kassa qaytaradi"
```

---

## Task 4: Z-hisobot naqd — refund (`z_cash_summary.py`)

**Files:**
- Modify: `app/utils/z_cash_summary.py` (`compute_z_cash_summary`)

- [ ] **Step 1: Migratsiya** — `cash_expenses_total` filtridagi `Payment.category.in_(("expense", "expense_doc", "other"))` ga `"sale_return"` qo'sh:
```python
    cash_expenses_total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        *exp_filters, Payment.category.in_(("expense", "expense_doc", "other", "sale_return")),
    ).scalar() or 0.0
```
(Shunda smena naqd chiqimiga refund kiradi → Z naqd qoldiq to'g'ri.)

- [ ] **Step 2: Sintaksis + testlar**

Run: `python -c "import ast; ast.parse(open(r'app/utils/z_cash_summary.py', encoding='utf-8').read()); print('OK')"`
Run: `python -m pytest tests/ -q`
Expected: OK

- [ ] **Step 3: Commit**
```bash
git add app/utils/z_cash_summary.py
git commit -m "fix(z-report): sale_return refund naqd chiqimga kirsin"
```

---

## Task 5: Data fix — `backfill_return_refunds.py`

**Files:**
- Create: `scripts/backfill_return_refunds.py`

- [ ] **Step 1: Skript yoz** (dry-run/apply) — mavjud sof qaytarishlar (return_sale, child-sale'siz, status NOT cancelled), note'dan original sotuvni topib refund hisoblaydi:
```python
"""Mavjud sof POS qaytarishlar uchun yetishmayotgan refund Payment'ni yozadi.
Default DRY-RUN. --apply bilan yozadi (backup oling!).
"""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from app.models.database import SessionLocal, Order, Payment
from app.services.refund_service import compute_return_refund
from app.services.finance_service import sync_cash_balance
from app.services.partner_balance_service import recompute_partner_balance

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    try:
        rets = db.query(Order).filter(Order.type == "return_sale",
                                      Order.status.notin_(["cancelled", "draft"])).all()
        plan = []
        for r in rets:
            # Exchange (child sale) bo'lsa — o'tkazib yuborish
            if db.query(Order.id).filter(Order.parent_order_id == r.id).first():
                continue
            # Allaqachon refund bor bo'lsa — o'tkazish
            if db.query(Payment.id).filter(Payment.order_id == r.id, Payment.category == "sale_return").first():
                continue
            # Original sotuv: note "... {S-number}" dan
            sale = None
            note = (r.note or "")
            for tok in note.replace(":", " ").replace("->", " ").split():
                if tok.startswith(("S-", "AGT-")):
                    sale = db.query(Order).filter(Order.number == tok, Order.type == "sale").first()
                    if sale:
                        break
            if not sale:
                print(f"  {r.number}: original sotuv topilmadi (note={note!r}) — o'tkazildi")
                continue
            lines = [(it.product_id, it.quantity) for it in r.items]
            info = compute_return_refund(db, sale, lines)
            if info["refund_cash"] > 0 and info["refund_cash_register_id"]:
                plan.append((r, sale, info))
        print("="*80)
        print(f"RETURN REFUND BACKFILL — {'APPLY' if APPLY else 'DRY-RUN'} | {len(plan)} ta")
        for r, sale, info in plan:
            print(f"  {r.number} (sotuv {sale.number}): refund {info['refund_cash']:,.0f} kassa#{info['refund_cash_register_id']}")
        if APPLY:
            for r, sale, info in plan:
                _today = datetime.now().strftime('%Y%m%d')
                _last = db.query(Payment).filter(Payment.number.like(f"PAY-{_today}-%")).order_by(Payment.number.desc()).first()
                _seq = (int(_last.number.split("-")[-1]) + 1) if (_last and _last.number) else 1
                db.add(Payment(number=f"PAY-{_today}-{_seq:04d}", date=datetime.now(), type="expense",
                               category="sale_return", payment_type="cash", status="confirmed",
                               partner_id=sale.partner_id, order_id=r.id,
                               cash_register_id=info["refund_cash_register_id"], amount=info["refund_cash"],
                               description=f"Qaytarish refund (backfill): {r.number} ({sale.number})"))
                db.flush()
                sync_cash_balance(db, info["refund_cash_register_id"])
                if sale.partner_id:
                    recompute_partner_balance(db, sale.partner_id, reason="sale_return_refund_backfill", ref=r.number)
            db.commit()
            print(f"\n[APPLIED] {len(plan)} refund yozildi.")
        else:
            print("\n[DRY-RUN] Hech narsa yozilmadi.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run (live, read-only)**

Run: `python scripts/backfill_return_refunds.py`
Expected: 2 ta (S-0197 ~500k, R-0601 ~30k) ko'rinadi. Hech narsa yozilmaydi.

- [ ] **Step 3: Commit**
```bash
git add scripts/backfill_return_refunds.py
git commit -m "feat(refund): mavjud qaytarishlar uchun refund backfill skript"
```

---

## Task 6: To'liq test + smoke
- [ ] `python -m pytest tests/ -q` → faqat 4 baseline fail
- [ ] `python -m pytest tests/test_endpoints_smoke.py tests/test_smoke.py -v` → yashil
- [ ] Har o'zgargan fayl AST tekshiruvi → OK

---

## Task 7: Deploy (tungi oyna, controller + foydalanuvchi)
> Subagent EMAS.
- [ ] **Backup** — `totli_holva.db.bak_pre_return_refund_20260602`
- [ ] Backfill dry-run ko'rsat → tasdiq
- [ ] Backfill apply — `python scripts/backfill_return_refunds.py --apply`
- [ ] Server restart (DCOM kill 8080 + schtasks run)
- [ ] Post-smoke: server UP + yangi qaytarish yaratib refund kassadan chiqishini tekshir
- [ ] Rollback: backup + git revert

---

## Self-Review natijasi
**Spec coverage:** compute_return_refund (T1), return yaratish refund + chegirmali total + exchange guard (T2), revert refund o'chirish (T3), z_cash_summary (T4), data fix (T5), test (T6), deploy (T7) — barcha spec bo'limlari qoplangan. ✅
**Placeholder scan:** aniq file:line + to'liq kod; PAY raqami generatsiyasi ko'rsatilgan. ✅
**Type consistency:** `compute_return_refund(db, sale, returned_lines)->dict{refund_cash, return_total, refund_cash_register_id, ratio}` — barcha task'larda izchil. ✅
