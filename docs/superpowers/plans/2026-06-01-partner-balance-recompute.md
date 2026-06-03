# Partner Balans Recompute Pattern — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `partner.balance` keshini inkremental mutatsiya o'rniga manba-hujjatlardan qayta quriladigan (recompute) qilib, drift'ni ildizdan yo'qotish + USD konvertatsiyani to'g'rilash.

**Architecture:** Yangi `app/services/partner_balance_service.py` ikki funksiya beradi: `compute_partner_balance` (hujjatlardan kanonik balans) va `recompute_partner_balance` (compute → set → audit log, commit qilmaydi). 25 ta qo'lda mutatsiya shu recompute chaqiruvi bilan almashtiriladi. `_build_partner_movements` yopilish balansi shu kanonik summani ishlatadi (display === kesh). Bir martalik backfill barcha balansni qayta quradi.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2.0, SQLite, pytest (in-memory DB fixtures `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-06-01-partner-balance-recompute-design.md`

---

## Fayl tuzilishi

| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/services/partner_balance_service.py` | compute + recompute + audit | YANGI |
| `tests/test_partner_balance_service.py` | unit + regressiya testlar | YANGI |
| `app/routes/reports.py` | `_build_partner_movements` kanonik sum | Modify |
| `app/routes/sales.py` | 5 mutatsiya → recompute | Modify |
| `app/routes/delivery_routes.py` | 9 mutatsiya → recompute | Modify |
| `app/routes/qoldiqlar.py` | 4 mutatsiya → recompute | Modify |
| `app/routes/finance.py` | 2 mutatsiya → recompute (USD bug) | Modify |
| `app/routes/api_driver_ops.py` | 1 mutatsiya → recompute | Modify |
| `app/routes/partners.py` | merge → recompute primary | Modify |
| `app/services/document_service.py` | 2 mutatsiya → recompute | Modify |
| `app/services/purchase_return_service.py` | 2 mutatsiya → recompute | Modify |
| `scripts/backfill_partner_balances.py` | bir martalik backfill + dry-run | YANGI |

**Belgi konvensiyasi (butun reja bo'yicha):** `partner.balance` musbat = mijoz bizga qarzdor; manfiy = biz partnerga qarzdormiz.

---

## Task 1: Kanonik formula — `compute_partner_balance` (valyutasiz, asosiy)

**Files:**
- Create: `app/services/partner_balance_service.py`
- Test: `tests/test_partner_balance_service.py`

- [ ] **Step 1: Failing test yoz**

`tests/test_partner_balance_service.py`:
```python
from datetime import datetime
from app.models.database import (
    Partner, Order, Payment, Purchase,
    PartnerBalanceDoc, PartnerBalanceDocItem, PurchaseReturn,
)
from app.services.partner_balance_service import compute_partner_balance


def _partner(db, balance=0):
    p = Partner(name="P", phone="+1", balance=balance, credit_limit=0, is_active=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


def test_compute_empty_partner_is_zero(db):
    p = _partner(db, balance=999)  # stored noto'g'ri bo'lsa ham
    assert compute_partner_balance(db, p.id) == 0.0


def test_compute_sale_adds_total(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed",
                 total=100000, date=datetime(2026, 6, 1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 100000.0


def test_compute_return_sale_subtracts(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026,6,1)))
    db.add(Order(partner_id=p.id, type="return_sale", status="confirmed", total=30000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 70000.0


def test_compute_income_payment_subtracts(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026,6,1)))
    db.add(Payment(partner_id=p.id, type="income", status="confirmed", amount=40000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 60000.0


def test_compute_expense_payment_adds(db):
    p = _partner(db)
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed", amount=50000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 50000.0


def test_compute_purchase_subtracts_total_plus_expenses(db):
    p = _partner(db)
    db.add(Purchase(partner_id=p.id, status="confirmed", total=80000, total_expenses=5000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == -85000.0


def test_compute_balance_doc_signed(db):
    p = _partner(db)
    doc = PartnerBalanceDoc(number="KNT-1", status="confirmed", date=datetime(2026,6,1))
    db.add(doc); db.flush()
    db.add(PartnerBalanceDocItem(doc_id=doc.id, partner_id=p.id, balance=-200000))
    db.commit()
    assert compute_partner_balance(db, p.id) == -200000.0


def test_compute_purchase_return_adds(db):
    p = _partner(db)
    db.add(Purchase(partner_id=p.id, status="confirmed", total=80000, total_expenses=0, date=datetime(2026,6,1)))
    db.add(PurchaseReturn(partner_id=p.id, status="confirmed", total=20000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == -60000.0


def test_compute_ignores_cancelled_and_draft(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="cancelled", total=100000, date=datetime(2026,6,1)))
    db.add(Order(partner_id=p.id, type="sale", status="draft", total=100000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 0.0


def test_compute_includes_null_status_payment(db):
    p = _partner(db)
    db.add(Payment(partner_id=p.id, type="expense", status=None, amount=10000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 10000.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `pytest tests/test_partner_balance_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.partner_balance_service'`

- [ ] **Step 3: Minimal implementatsiya**

`app/services/partner_balance_service.py`:
```python
"""Partner balans — manba-hujjatlardan qayta quriladigan kesh (recompute pattern).

Kanonik formula = reports._build_partner_movements yopilish balansi.
Belgi: musbat = mijoz bizga qarzdor; manfiy = biz partnerga qarzdormiz.
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import (
    Partner, Order, Payment, Purchase,
    PartnerBalanceDoc, PartnerBalanceDocItem, PurchaseReturn,
)


def compute_partner_balance(db: Session, partner_id: int) -> float:
    """Partner balansini hujjatlardan qayta hisoblaydi (kanonik haqiqat).

    faqat confirmed (to'lov uchun status NULL ham), cancelled/draft chiqarib.
    """
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        return 0.0

    total = 0.0

    # Sotuv (+total) / qaytarish (-total)
    for o in db.query(Order).filter(
        Order.partner_id == partner_id,
        Order.type.in_(["sale", "return_sale"]),
        Order.status.notin_(["cancelled", "draft"]),
    ):
        if o.type == "sale":
            total += float(o.total or 0)
        else:
            total -= float(o.total or 0)

    # To'lovlar: income -amount, expense +amount
    for p in db.query(Payment).filter(
        Payment.partner_id == partner_id,
        or_(Payment.status == "confirmed", Payment.status.is_(None)),
    ):
        amt = float(p.amount or 0)
        if p.type == "income":
            total -= amt
        else:
            total += amt

    # Xaridlar -(total+total_expenses)
    for p in db.query(Purchase).filter(
        Purchase.partner_id == partner_id,
        Purchase.status == "confirmed",
    ):
        total -= float((p.total or 0) + (p.total_expenses or 0))

    # Kontragent qoldiq hujjatlari (signed)
    for item in (
        db.query(PartnerBalanceDocItem)
        .join(PartnerBalanceDoc, PartnerBalanceDocItem.doc_id == PartnerBalanceDoc.id)
        .filter(
            PartnerBalanceDocItem.partner_id == partner_id,
            PartnerBalanceDoc.status == "confirmed",
        )
    ):
        total += float(item.balance or 0)

    # Yetkazib beruvchiga qaytarish (+total)
    for d in db.query(PurchaseReturn).filter(
        PurchaseReturn.partner_id == partner_id,
        PurchaseReturn.status == "confirmed",
    ):
        total += float(d.total or 0)

    return total
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `pytest tests/test_partner_balance_service.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/partner_balance_service.py tests/test_partner_balance_service.py
git commit -m "feat(balance): compute_partner_balance kanonik formula + testlar"
```

---

## Task 2: USD konvertatsiya — to'lovlar so'mga aylantiriladi (#7/#8)

**Files:**
- Modify: `app/services/partner_balance_service.py`
- Test: `tests/test_partner_balance_service.py`

- [ ] **Step 1: Failing test yoz** (faylga qo'sh)

```python
from datetime import date
from app.models.database import CashRegister, ExchangeRate


def test_compute_converts_usd_expense_payment(db):
    p = _partner(db)
    usd = CashRegister(name="Asosiy $", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", rate=12000, effective_date=date(2026,1,1)))
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed",
                   amount=100, cash_register_id=usd.id, date=datetime(2026,6,1)))
    db.commit()
    # 100 USD * 12000 = 1,200,000 so'm
    assert compute_partner_balance(db, p.id) == 1200000.0


def test_compute_uzs_payment_not_converted(db):
    p = _partner(db)
    uzs = CashRegister(name="Naqd", payment_type="naqd", currency="UZS", is_active=True, opening_balance=0)
    db.add(uzs); db.flush()
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed",
                   amount=50000, cash_register_id=uzs.id, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 50000.0


def test_compute_usd_no_rate_uses_raw_amount(db):
    # Kurs umuman yo'q — xom amount ishlatiladi (to'lov yo'qolmasligi uchun)
    p = _partner(db)
    usd = CashRegister(name="Asosiy $", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed",
                   amount=100, cash_register_id=usd.id, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 100.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `pytest tests/test_partner_balance_service.py::test_compute_converts_usd_expense_payment -v`
Expected: FAIL — `assert 100.0 == 1200000.0`

- [ ] **Step 3: Implementatsiya — to'lov summasini so'mga aylantirish helper**

`app/services/partner_balance_service.py`: importlarga qo'sh va helper + to'lov loopini yangila:
```python
import logging
from app.services.currency_service import get_rate

logger = logging.getLogger(__name__)


def _payment_amount_uzs(db: Session, payment: Payment) -> float:
    """To'lov summasini so'mda qaytaradi. USD kassa bo'lsa kurs bilan aylantiradi."""
    amt = float(payment.amount or 0)
    cr = payment.cash_register
    currency = (getattr(cr, "currency", None) or "UZS") if cr else "UZS"
    if currency == "UZS":
        return amt
    on_date = payment.date.date() if payment.date else None
    rate = get_rate(db, currency, "UZS", on_date)
    if not rate or rate <= 0:
        logger.warning(
            "partner_balance: %s to'lov #%s uchun %s->UZS kurs topilmadi, xom amount ishlatildi",
            currency, getattr(payment, "id", "?"), currency,
        )
        return amt
    return amt * rate
```

To'lov loopini almashtir:
```python
    for p in db.query(Payment).filter(
        Payment.partner_id == partner_id,
        or_(Payment.status == "confirmed", Payment.status.is_(None)),
    ):
        amt = _payment_amount_uzs(db, p)
        if p.type == "income":
            total -= amt
        else:
            total += amt
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `pytest tests/test_partner_balance_service.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/partner_balance_service.py tests/test_partner_balance_service.py
git commit -m "feat(balance): USD kassa to'lovlarini so'mga aylantirish (#7/#8)"
```

---

## Task 3: `recompute_partner_balance` — set + audit log

**Files:**
- Modify: `app/services/partner_balance_service.py`
- Test: `tests/test_partner_balance_service.py`

- [ ] **Step 1: Failing test yoz**

```python
from app.models.database import AuditLog


def test_recompute_sets_balance_and_returns_old_new(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=999)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026,6,1)))
    db.commit()
    old, new = recompute_partner_balance(db, p.id, reason="sale_confirm")
    db.commit()
    assert old == 999.0
    assert new == 100000.0
    db.refresh(p)
    assert p.balance == 100000.0


def test_recompute_writes_audit_log(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=50000, date=datetime(2026,6,1)))
    db.commit()
    recompute_partner_balance(db, p.id, reason="sale_confirm", ref="S-0001", actor="admin")
    db.commit()
    logs = db.query(AuditLog).filter(AuditLog.entity_type == "partner_balance").all()
    assert len(logs) == 1
    assert logs[0].entity_id == p.id
    assert logs[0].action == "recompute"
    assert "sale_confirm" in (logs[0].details or "")
    assert logs[0].entity_number == "S-0001"


def test_recompute_idempotent(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=70000, date=datetime(2026,6,1)))
    db.commit()
    recompute_partner_balance(db, p.id, reason="x"); db.commit()
    old, new = recompute_partner_balance(db, p.id, reason="x"); db.commit()
    assert old == new == 70000.0


def test_recompute_confirm_revert_confirm_no_drift(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    o = Order(partner_id=p.id, type="sale", status="confirmed", total=80000, date=datetime(2026,6,1))
    db.add(o); db.commit()
    recompute_partner_balance(db, p.id, reason="confirm"); db.commit()
    db.refresh(p); assert p.balance == 80000.0
    o.status = "cancelled"; db.commit()
    recompute_partner_balance(db, p.id, reason="revert"); db.commit()
    db.refresh(p); assert p.balance == 0.0
    o.status = "confirmed"; db.commit()
    recompute_partner_balance(db, p.id, reason="reconfirm"); db.commit()
    db.refresh(p); assert p.balance == 80000.0
```

- [ ] **Step 2: Test fail bo'lishini tasdiqla**

Run: `pytest tests/test_partner_balance_service.py -k recompute -v`
Expected: FAIL — `ImportError: cannot import name 'recompute_partner_balance'`

- [ ] **Step 3: Implementatsiya**

`app/services/partner_balance_service.py` ga qo'sh:
```python
from app.models.database import AuditLog


def recompute_partner_balance(db: Session, partner_id: int, *, reason: str,
                              ref: str = None, actor: str = None) -> tuple:
    """Partner balansini qayta hisoblab set qiladi + audit log yozadi.

    db.commit() CHAQIRMAYDI — chaqiruvchining tranzaksiyasiga qo'shiladi (atomik).
    Qaytaradi: (old_balance, new_balance).
    """
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        return (0.0, 0.0)
    old = float(partner.balance or 0)
    new = compute_partner_balance(db, partner_id)
    partner.balance = new
    db.add(AuditLog(
        user_name=actor or "system",
        action="recompute",
        entity_type="partner_balance",
        entity_id=partner_id,
        entity_number=ref,
        details=f"reason={reason}; {old:.2f} -> {new:.2f}; delta={new - old:+.2f}",
    ))
    return (old, new)
```

- [ ] **Step 4: Testlar o'tishini tasdiqla**

Run: `pytest tests/test_partner_balance_service.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/partner_balance_service.py tests/test_partner_balance_service.py
git commit -m "feat(balance): recompute_partner_balance + audit log"
```

---

## Task 4: `_build_partner_movements` display === kesh regressiya

**Files:**
- Modify: `app/routes/reports.py` (`_build_partner_movements` oxiri — yopilish balansi hisobi)
- Test: `tests/test_partner_balance_service.py`

**Maqsad:** reconciliation yopilish balansi `compute_partner_balance` bilan AYNAN teng bo'lsin. Reports.py allaqachon rows'ni debit/credit bilan quradi; yopilish = opening + Σ(debit−credit). Bu kanonik formulaga teng bo'lishi shart. Regressiya testi shuni qulflaydi. Reports.py'da USD konvertatsiya hozir YO'Q — display ham to'g' rilanishi uchun reports.py'dagi to'lov debit/credit'iga `_payment_amount_uzs` qo'llanadi.

- [ ] **Step 1: Regressiya test yoz**

```python
def test_reconciliation_closing_equals_compute(db):
    from app.routes.reports import _build_partner_movements
    from datetime import datetime as _dt
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=_dt(2026,6,1)))
    db.add(Payment(partner_id=p.id, type="income", status="confirmed", amount=30000, date=_dt(2026,6,1)))
    db.add(Purchase(partner_id=p.id, status="confirmed", total=20000, total_expenses=0, date=_dt(2026,6,1)))
    db.commit()
    rows, od, oc = _build_partner_movements(db, p.id, _dt(2026,1,1), _dt(2026,12,31), period_only=False)
    closing = sum(float(r["debit"]) - float(r["credit"]) for r in rows)
    assert abs(closing - compute_partner_balance(db, p.id)) < 0.01
```

- [ ] **Step 2: Test fail/pass holatini tekshir**

Run: `pytest tests/test_partner_balance_service.py::test_reconciliation_closing_equals_compute -v`
Expected: dastlab PASS bo'lishi mumkin (formulalar mos), lekin USD to'lov qatorida FARQ chiqishi mumkin. Agar PASS bo'lsa — Step 3'da faqat USD konvertatsiyani reports'ga qo'shamiz va testga USD qatori qo'shamiz.

- [ ] **Step 3: Reports'da to'lov summasini so'mga aylantirish**

`app/routes/reports.py` `_build_partner_movements` ichida import qo'sh (fayl boshida yoki funksiya ichida):
```python
from app.services.partner_balance_service import _payment_amount_uzs
```
To'lov loopida (1964-1986 atrofida) `float(p.amount or 0)` o'rniga `_payment_amount_uzs(db, p)` ishlat — ikkala (income credit / expense debit) joyда:
```python
        amt_uzs = _payment_amount_uzs(db, p)
        if p.type == "income":
            rows.append({..., "debit": 0.0, "credit": amt_uzs})
        else:
            rows.append({..., "debit": amt_uzs, "credit": 0.0})
```
(qolgan maydonlar o'zgarmaydi.)

- [ ] **Step 4: USD qatorli regressiya testini kengaytir va o'tkaz**

```python
def test_reconciliation_closing_equals_compute_with_usd(db):
    from app.routes.reports import _build_partner_movements
    from datetime import datetime as _dt, date as _d
    from app.models.database import CashRegister, ExchangeRate
    p = _partner(db)
    usd = CashRegister(name="$", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", rate=12000, effective_date=_d(2026,1,1)))
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed", amount=100, cash_register_id=usd.id, date=_dt(2026,6,1)))
    db.commit()
    rows, od, oc = _build_partner_movements(db, p.id, _dt(2026,1,1), _dt(2026,12,31), period_only=False)
    closing = sum(float(r["debit"]) - float(r["credit"]) for r in rows)
    assert abs(closing - compute_partner_balance(db, p.id)) < 0.01
    assert abs(closing - 1200000.0) < 0.01
```

Run: `pytest tests/test_partner_balance_service.py -v`
Expected: barchasi passed

- [ ] **Step 5: Commit**

```bash
git add app/routes/reports.py tests/test_partner_balance_service.py
git commit -m "feat(balance): reconciliation USD konvertatsiya + display==kesh regressiya"
```

---

## Call-site migration — umumiy pattern (Task 5-11 uchun)

Har bir migrating joyda **qoidalar:**
1. Hujjat o'zgarishini (Order/Payment/Purchase/... maydonlari, status) bajar.
2. Eski `partner.balance += / -= / = previous_balance` **qatorini o'chir**.
3. Hujjat o'zgarishi flush bo'lgach chaqir:
   `from app.services.partner_balance_service import recompute_partner_balance`
   `recompute_partner_balance(db, partner_id, reason="<kontekst>", ref=<hujjat raqami>, actor=<current_user.username yoki None>)`
4. `previous_partner_balance` / `previous_balance` snapshot O'QISH/YOZISH mantiqi olib tashlanadi (revert endi recompute bilan to'g'ri).
5. **Bulk** (ko'p qatorli) operatsiyada: ta'sirlangan `partner_id`'larni `set()`'ga yig', oxirida har biriga **1 marta** `recompute`.
6. Migratsiyadan keyin shu fayl bilan bog'liq mavjud testlar (`test_revert_balance.py`, `test_purchase_return.py`, `test_sales_metrics.py`, `test_dispatch_flow.py`, `test_exchange_driver_flow.py`) **o'zgarmasdan** o'tishi shart (yoki snapshot kutgan testlar yangilanadi).

**Verifikatsiya har task oxirida:**
Run: `pytest tests/ -q`
Expected: barcha mavjud testlar yashil (yoki snapshot-kutgan testlar yangilangan).

---

## Task 5: `document_service.py` — xarid confirm/revert (2 joy)

**Files:**
- Modify: `app/services/document_service.py:137` (confirm: `partner.balance -= total_with_expenses`), `:333` (revert: `partner.balance += total_with_expenses`)
- Test: `tests/test_partner_balance_service.py` (yangi integratsiya testi)

- [ ] **Step 1: Failing integratsiya test yoz**

```python
def test_purchase_confirm_recomputes_balance(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    pur = Purchase(partner_id=p.id, status="confirmed", total=60000, total_expenses=0, date=datetime(2026,6,1))
    db.add(pur); db.flush()
    recompute_partner_balance(db, p.id, reason="purchase_confirm"); db.commit()
    db.refresh(p)
    assert p.balance == -60000.0
```

- [ ] **Step 2: Test holatini tekshir**

Run: `pytest tests/test_partner_balance_service.py::test_purchase_confirm_recomputes_balance -v`
Expected: PASS (recompute mustaqil ishlaydi) — bu test recompute kontraktini qulflaydi.

- [ ] **Step 3: `document_service.py` migratsiya**

`:137` confirm bloki — `partner.balance -= total_with_expenses` qatorini o'chir, o'rniga purchase saqlangach:
```python
from app.services.partner_balance_service import recompute_partner_balance
db.flush()
recompute_partner_balance(db, partner.id, reason="purchase_confirm",
                          ref=getattr(purchase, "number", None))
```
`:333` revert bloki — `partner.balance += total_with_expenses` qatorini o'chir, status `cancelled` qilingach:
```python
db.flush()
recompute_partner_balance(db, partner.id, reason="purchase_revert",
                          ref=getattr(purchase, "number", None))
```
(O'zgaruvchi nomlari mahalliy kontekstga moslanadi — `partner`/`purchase` mavjud.)

- [ ] **Step 4: Testlar**

Run: `pytest tests/ -q`
Expected: barchasi yashil

- [ ] **Step 5: Commit**

```bash
git add app/services/document_service.py tests/test_partner_balance_service.py
git commit -m "refactor(balance): xarid confirm/revert -> recompute"
```

---

## Task 6: `purchase_return_service.py` — qaytarish confirm/cancel (2 joy)

**Files:**
- Modify: `app/services/purchase_return_service.py:62` (confirm: `partner.balance = balance + total`), `:102` (cancel: `partner.balance = balance - total`)

- [ ] **Step 1: Mavjud test bilan ishlash**

`tests/test_purchase_return.py` mavjud — qaytarish confirm/cancel balansga ta'sirini tekshiradi. Avval o'qib qaysi qiymat kutilishini ko'r.

Run: `pytest tests/test_purchase_return.py -v`
Expected: hozir PASS (eski mantiq bilan).

- [ ] **Step 2: `purchase_return_service.py` migratsiya**

`:62` confirm — `partner.balance = (partner.balance or 0) + float(doc.total or 0)` o'chir, stock o'zgarishidan keyin:
```python
from app.services.partner_balance_service import recompute_partner_balance
db.flush()
recompute_partner_balance(db, doc.partner_id, reason="purchase_return_confirm", ref=doc.number)
```
`:102` cancel — `partner.balance = (partner.balance or 0) - float(doc.total or 0)` o'chir, status cancelled qilingach:
```python
db.flush()
recompute_partner_balance(db, doc.partner_id, reason="purchase_return_cancel", ref=doc.number)
```

- [ ] **Step 3: Testlar**

Run: `pytest tests/test_purchase_return.py tests/test_partner_balance_service.py -v`
Expected: barchasi yashil. Agar `test_purchase_return.py` aniq oraliq stored qiymatga tayanган bo'lsa — recompute yakuniy qiymati to'g'ri bo'lsa testni shunga moslab yangilang (kommentariya bilan).

- [ ] **Step 4: Commit**

```bash
git add app/services/purchase_return_service.py tests/
git commit -m "refactor(balance): xarid qaytarish confirm/cancel -> recompute"
```

---

## Task 7: `finance.py` — to'lov apply (2 joy, USD bug yo'qoladi)

**Files:**
- Modify: `app/routes/finance.py:830,833` (`_payment_apply_balance`: income `-= amount*sign`, expense `+= amount*sign`)

- [ ] **Step 1: Failing test yoz** (yangi)

```python
def test_payment_apply_uses_recompute_with_usd(db):
    from app.services.partner_balance_service import recompute_partner_balance
    from app.models.database import CashRegister, ExchangeRate
    from datetime import date as _d
    p = _partner(db, balance=0)
    usd = CashRegister(name="$", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", rate=12000, effective_date=_d(2026,1,1)))
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed", amount=100, cash_register_id=usd.id, date=datetime(2026,6,1)))
    db.commit()
    recompute_partner_balance(db, p.id, reason="payment_confirm"); db.commit()
    db.refresh(p)
    assert p.balance == 1200000.0   # xom 100 emas (eski bug)
```

- [ ] **Step 2: Test holatini tekshir**

Run: `pytest tests/test_partner_balance_service.py::test_payment_apply_uses_recompute_with_usd -v`
Expected: PASS (recompute to'g'ri konvertatsiya qiladi).

- [ ] **Step 3: `finance.py` `_payment_apply_balance` migratsiya**

`_payment_apply_balance` (816-833) — `partner.balance` ni `± amount*sign` qiladigan ikki tarmoqni o'chir. Funksiya endi shunchaki to'lovni saqlab, recompute chaqirsin:
```python
from app.services.partner_balance_service import recompute_partner_balance
# ... to'lov yozilgach / status o'zgargach:
db.flush()
recompute_partner_balance(db, partner.id, reason=f"payment_{payment.type}",
                          ref=getattr(payment, "number", None),
                          actor=getattr(current_user, "username", None) if 'current_user' in dir() else None)
```
Revert/o'chirish yo'llarida ham (agar `_payment_apply_balance` teskari ishlatilsa) — sign mantiqini olib tashlab, to'lov `cancelled`/o'chirilgach recompute chaqir. (Funksiya imzosi va chaqiruvchilarini tekshirib moslang; `current_user` mavjud bo'lmasa `actor=None`.)

- [ ] **Step 4: Testlar**

Run: `pytest tests/ -q`
Expected: yashil

- [ ] **Step 5: Commit**

```bash
git add app/routes/finance.py tests/test_partner_balance_service.py
git commit -m "fix(balance): to'lov->partner recompute (USD konvertatsiya #7/#8)"
```

---

## Task 8: `sales.py` — sotuv confirm/revert/edit (5 joy)

**Files:**
- Modify: `app/routes/sales.py:63,66` (revert: `= previous_partner_balance`, `-= debt`), `:881` (confirm: `+= debt`), `:3744` (`+= total`), `:4280` (`+= amount`)

- [ ] **Step 1: Mavjud testlarni ko'r**

`tests/test_revert_balance.py`, `tests/test_sales_metrics.py`, `tests/test_atomic_confirm.py` sotuv balansiga tegadi.

Run: `pytest tests/test_revert_balance.py -v`
Expected: hozir PASS.

- [ ] **Step 2: `sales.py` migratsiya — confirm (`:881`)**

`partner.balance = float(partner.balance or 0) + float(order.debt)` o'chir; order saqlangach:
```python
from app.services.partner_balance_service import recompute_partner_balance
db.flush()
recompute_partner_balance(db, order.partner_id, reason="sale_confirm", ref=order.number,
                          actor=getattr(current_user, "username", None))
```

- [ ] **Step 3: `sales.py` migratsiya — revert (`:63,66`)**

`previous_partner_balance` snapshot yo'li (`partner.balance = order.previous_partner_balance` va `-= debt`) **butunlay** o'chiriladi; order `cancelled` qilingach:
```python
db.flush()
recompute_partner_balance(db, order.partner_id, reason="sale_revert", ref=order.number,
                          actor=getattr(current_user, "username", None))
```
`Order.previous_partner_balance` yozilishini ham olib tashla (boshqa joyda o'qilmaydigan bo'lsa). Agar boshqa joy o'qisa — qoldir, lekin balansga ishlatma.

- [ ] **Step 4: `sales.py` migratsiya — `:3744` va `:4280`**

Har ikkala joyda `partner.balance += ...` o'chir, mos hujjat saqlangach `recompute_partner_balance(db, <partner_id>, reason="sale_edit"/"sale_adjust", ref=...)`. Kontekstini o'qib reason ber.

- [ ] **Step 5: Testlar**

Run: `pytest tests/ -q`
Expected: yashil. `test_revert_balance.py` snapshot-asosli aniq qiymat kutsa — yakuniy balans to'g'ri bo'lsa testni recompute natijasiga moslab yangila (izoh bilan: "recompute pattern — snapshot o'rniga").

- [ ] **Step 6: Commit**

```bash
git add app/routes/sales.py tests/
git commit -m "refactor(balance): sotuv confirm/revert/edit -> recompute (snapshot olib tashlandi)"
```

---

## Task 9: `delivery_routes.py` — yetkazish/agent to'lov (9 joy)

**Files:**
- Modify: `app/routes/delivery_routes.py:596,599` (revert), `:1060,1239,1280,1351,1376,1399,1435` (agent to'lov/o'zgarish)

- [ ] **Step 1: Mavjud testlarni ko'r**

`tests/test_dispatch_flow.py`, `tests/test_exchange_driver_flow.py` shu yo'llarni qamraydi.

Run: `pytest tests/test_dispatch_flow.py tests/test_exchange_driver_flow.py -v`
Expected: hozir PASS.

- [ ] **Step 2: Migratsiya — har 9 joy**

Har joyda `partner.balance ± ...` o'chir, mos operatsiya (deliver/agent_payment confirm/edit/revert) bajarilgach recompute chaqir. **Bulk** (`:596,599` yetkazish reverti va agent to'lov ko'p qatorli bo'lsa) — ta'sirlangan partner_id'larni yig'ib oxirida 1 marta:
```python
from app.services.partner_balance_service import recompute_partner_balance
affected = set()
# ... loop: affected.add(partner_obj.id)
db.flush()
for pid in affected:
    recompute_partner_balance(db, pid, reason="delivery_deliver", actor=getattr(current_user, "username", None))
```
Bitta partnerli joylarda to'g'ridan-to'g'ri 1 chaqiruv. `:1280,1351,1376,1399,1435` agent to'lov yaratish/tahrir/o'chirish — mos `reason="agent_payment_*"`.

- [ ] **Step 3: Testlar**

Run: `pytest tests/ -q`
Expected: yashil (kerak bo'lsa snapshot-kutgan testlarni recompute natijasiga moslab yangila).

- [ ] **Step 4: Commit**

```bash
git add app/routes/delivery_routes.py tests/
git commit -m "refactor(balance): yetkazish/agent to'lov -> recompute"
```

---

## Task 10: `api_driver_ops.py` (1) + `qoldiqlar.py` (4) + `partners.py` merge (1)

**Files:**
- Modify: `app/routes/api_driver_ops.py:365`
- Modify: `app/routes/qoldiqlar.py:631,652,1332,1357`
- Modify: `app/routes/partners.py:528`

- [ ] **Step 1: `api_driver_ops.py:365` migratsiya**

`partner_obj.balance = ... + order.debt` o'chir, order deliver bo'lgach:
```python
from app.services.partner_balance_service import recompute_partner_balance
db.flush()
recompute_partner_balance(db, partner_obj.id, reason="driver_deliver", ref=getattr(order, "number", None))
```

- [ ] **Step 2: `qoldiqlar.py` migratsiya (4 joy)**

`:631` confirm (`partner.balance += item.balance`) va `:652` revert (`= item.previous_balance`): har item uchun emas — doc tasdiqlangach **ta'sirlangan partnerlar bo'yicha 1 martadan** recompute. Snapshot (`previous_balance`) o'qish/yozishni balansga ishlatma:
```python
from app.services.partner_balance_service import recompute_partner_balance
db.flush()
for pid in {it.partner_id for it in doc.items}:
    recompute_partner_balance(db, pid, reason="balance_doc_confirm", ref=doc.number)
```
Revert uchun `reason="balance_doc_revert"`. `:1332,1357` — boshqa partner.balance to'g'ridan-to'g'ri set yo'llari; kontekstni o'qib, mos hujjat saqlangach recompute bilan almashtir.

- [ ] **Step 3: `partners.py:528` merge migratsiya**

Dublikat→asosiy hujjatlar ko'chirilgach `primary.balance = (primary.balance or 0) + (o.balance or 0)` o'chir, o'rniga:
```python
from app.services.partner_balance_service import recompute_partner_balance
db.flush()
recompute_partner_balance(db, primary.id, reason="partner_merge", ref=str(primary.id))
```
(Hujjatlar primary'ga ko'chgani uchun recompute to'g'ri jami beradi.)

- [ ] **Step 4: Testlar**

Run: `pytest tests/ -q`
Expected: yashil

- [ ] **Step 5: Commit**

```bash
git add app/routes/api_driver_ops.py app/routes/qoldiqlar.py app/routes/partners.py
git commit -m "refactor(balance): driver/qoldiq/merge -> recompute (25 joy yakunlandi)"
```

---

## Task 11: Migratsiya yaxlitligi — global grep tekshiruvi

**Files:** (tekshiruv, kod o'zgarmaydi yoki qoldiq topiladi)

- [ ] **Step 1: Qolgan qo'lda mutatsiyalarni qidir**

Run (loyiha root): `grep -rnE "partner\w*\.balance\s*[-+]?=" app/ --include=*.py`
Expected: faqat `partner_balance_service.py:recompute` ichidagi `partner.balance = new` qatori qolishi kerak. Boshqa har qanday natija — qolgan migratsiya qilinmagan joy.

- [ ] **Step 2: Qoldiq bo'lsa — tegishli Task pattern bilan migratsiya qil, testlarni qayta yur.**

Run: `pytest tests/ -q`
Expected: yashil

- [ ] **Step 3: Commit (agar o'zgarish bo'lsa)**

```bash
git add -A
git commit -m "refactor(balance): qoldiq mutatsiyalar tozalandi"
```

---

## Task 12: Backfill skript — dry-run + apply

**Files:**
- Create: `scripts/backfill_partner_balances.py`

- [ ] **Step 1: Skript yoz (dry-run default, --apply bilan yozadi)**

`scripts/backfill_partner_balances.py`:
```python
"""Barcha partner balansini hujjatlardan qayta quradi.

Default: DRY-RUN (faqat hisobot). --apply bilan yozadi (avval backup oling!).

Ishlatish:
    python scripts/backfill_partner_balances.py            # dry-run hisobot
    python scripts/backfill_partner_balances.py --apply    # yozadi
"""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")

from app.models.database import SessionLocal, Partner
from app.services.partner_balance_service import compute_partner_balance, recompute_partner_balance

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    try:
        partners = db.query(Partner).order_by(Partner.id).all()
        changes = []
        for p in partners:
            stored = float(p.balance or 0)
            computed = compute_partner_balance(db, p.id)
            if abs(stored - computed) > 0.01:
                changes.append((p.id, p.name, stored, computed, computed - stored))
        changes.sort(key=lambda x: abs(x[4]), reverse=True)
        print(f"{'='*78}")
        print(f"PARTNER BALANS BACKFILL — {'APPLY' if APPLY else 'DRY-RUN'}")
        print(f"{'='*78}")
        print(f"Jami partner: {len(partners)} | o'zgaradigan: {len(changes)}")
        print(f"{'id':<6}{'nom':<28}{'stored':>14}{'computed':>14}{'delta':>14}")
        for pid, name, s, c, d in changes:
            print(f"{pid:<6}{(name or '')[:27]:<28}{s:>14,.0f}{c:>14,.0f}{d:>+14,.0f}")
        print(f"{'-'*78}")
        print(f"Jami delta (abs): {sum(abs(x[4]) for x in changes):,.0f}")
        if APPLY:
            for pid, name, s, c, d in changes:
                recompute_partner_balance(db, pid, reason="backfill_20260601")
            db.commit()
            print(f"\n[APPLIED] {len(changes)} partner balansi yozildi.")
        else:
            print(f"\n[DRY-RUN] Hech narsa yozilmadi. --apply bilan yozish uchun avval backup oling.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run yugurt (live DB, read-only)**

Run (PowerShell): `python scripts/backfill_partner_balances.py`
Expected: hisobot — 4 driftli partner (id=673,700,232,711) + boshqa farqlar ko'rinadi. HECH NARSA yozilmaydi.

- [ ] **Step 3: Foydalanuvchiga hisobotni ko'rsat — tasdiq kutiladi**

Hisobotni foydalanuvchiga yetkaz. Apply faqat tasdiqdan keyin (Task 14 deploy ichida, backup bilan).

- [ ] **Step 4: Commit (skript)**

```bash
git add scripts/backfill_partner_balances.py
git commit -m "feat(balance): backfill skript (dry-run/apply)"
```

---

## Task 13: To'liq test yugurtish + smoke

**Files:** (tekshiruv)

- [ ] **Step 1: Butun test paketi**

Run: `pytest tests/ -q`
Expected: barchasi yashil

- [ ] **Step 2: Smoke testlar**

Run: `pytest tests/test_endpoints_smoke.py tests/test_smoke.py -v`
Expected: yashil

- [ ] **Step 3: AST sintaksis tekshiruvi (barcha o'zgargan fayl)**

Run (PowerShell): har o'zgargan fayl uchun
`python -c "import ast; ast.parse(open(r'<path>', encoding='utf-8').read()); print('OK')"`
Expected: OK

---

## Task 14: Deploy (tungi oyna, subagent EMAS — foydalanuvchi nazorati)

**Files:** (deploy, kod o'zgarmaydi)

> Bu task'ni controller (asosiy Claude) foydalanuvchi bilan birga, tungi oynada bajaradi. Subagent buni bajarmaydi.

- [ ] **Step 1: Backup** — `python -c "import sqlite3; s=sqlite3.connect(r'\\server2220\d\TOTLI BI\totli_holva.db'); d=sqlite3.connect(r'\\server2220\d\TOTLI BI\totli_holva.db.bak_pre_balance_recompute_20260601'); s.backup(d); d.close(); s.close()"`
- [ ] **Step 2: Backfill dry-run'ni foydalanuvchiga ko'rsat → tasdiq**
- [ ] **Step 3: Backfill apply** — `python scripts/backfill_partner_balances.py --apply`
- [ ] **Step 4: Server restart** (DCOM CimSession: 8080 PID terminate + `schtasks /run /S server2220 /TN "TOTLI_BI_Server"`)
- [ ] **Step 5: Post-smoke** — server UP (HTTP 200) + bir nechta partner reconciliation == balance UI'da
- [ ] **Step 6: Rollback rejasi** — muammo bo'lsa: backup'ni tikla + `git revert`

---

## Self-Review natijasi (reja muallifi)

**Spec coverage:** compute (T1), USD (T2), recompute+audit (T3), display==kesh (T4), 25 call-site (T5-T11), backfill+dry-run (T12), testlar (T1-T4,T13), rollout (T14) — barcha spec bo'limlari qoplangan. ✅
**Placeholder scan:** call-site task'larida aniq file:line + pattern + worked example bor; mavhum "handle edge cases" yo'q. ✅
**Type consistency:** `compute_partner_balance(db, partner_id)->float`, `recompute_partner_balance(db, partner_id, *, reason, ref=None, actor=None)->(old,new)`, `_payment_amount_uzs(db, payment)->float` — barcha task'larda izchil. ✅
