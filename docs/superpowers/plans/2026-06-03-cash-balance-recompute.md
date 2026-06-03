# Kassa balans recompute — Implementatsiya rejasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Kassa balansini to'liq recompute-from-documents patterniga keltirish — audit izi, qoldiq hujjati snapshot drift fix, drift monitorga kassa.

**Architecture:** Kassada `cash_balance_formula` (formula) + `sync_cash_balance` (jim recompute) allaqachon bor. Yangi `recompute_cash_balance` (audit-yozadigan) qo'shiladi; qoldiq hujjati confirm/revert snapshot → opening-restore'ga o'tkaziladi (yangi `previous_opening` ustun); drift monitorga kassa bloki qo'shiladi.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest, Python 3.12. Server: `\\server2220\d\TOTLI BI`.

---

### Task 1: `recompute_cash_balance` funksiyasi

**Files:**
- Modify: `app/services/finance_service.py` (sync_cash_balance dan keyin, ~70-qator)
- Test: `tests/test_cash_recompute.py` (yangi)

- [ ] **Step 1: Failing test yozish**

`tests/test_cash_recompute.py`:
```python
import os
os.environ.setdefault("TOTLI_DB_FILE", ":memory:")
os.environ.setdefault("SECRET_KEY", "test")
from app.models.database import Base, engine, SessionLocal, CashRegister, AuditLog
from app.services.finance_service import recompute_cash_balance


def _fresh_db():
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_recompute_cash_balance_sets_and_audits():
    db = _fresh_db()
    try:
        c = CashRegister(name="Test kassa", opening_balance=1000.0, balance=999.0, currency="UZS")
        db.add(c); db.flush()
        old, new = recompute_cash_balance(db, c.id, reason="unit_test", ref="X-1", actor="tester")
        assert old == 999.0
        assert new == 1000.0          # opening + 0 income - 0 expense
        assert c.balance == 1000.0
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "cash_balance",
                                         AuditLog.entity_id == c.id).all()
        assert len(logs) == 1
        assert "reason=unit_test" in logs[0].details
        assert logs[0].user_name == "tester"
    finally:
        db.rollback(); db.close()
```

- [ ] **Step 2: Test fail bo'lishini tekshirish**

Run: `python -m pytest tests/test_cash_recompute.py::test_recompute_cash_balance_sets_and_audits -v`
Expected: FAIL — `ImportError: cannot import name 'recompute_cash_balance'`

- [ ] **Step 3: Implementatsiya**

`app/services/finance_service.py` da `sync_cash_balance` dan keyin qo'shish:
```python
def recompute_cash_balance(db: Session, cash_id: int, *, reason: str,
                           ref: str = None, actor: str = None) -> tuple:
    """Kassa balansini formuladan qayta hisoblab set qiladi + AuditLog yozadi.

    db.commit() CHAQIRMAYDI — chaqiruvchining tranzaksiyasiga qo'shiladi (atomik).
    Qaytaradi: (old_balance, new_balance).
    """
    from app.models.database import AuditLog
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return (0.0, 0.0)
    old = float(cash.balance or 0)
    new, _, _ = cash_balance_formula(db, cash_id)
    cash.balance = new
    db.add(AuditLog(
        user_name=actor or "system",
        action="recompute",
        entity_type="cash_balance",
        entity_id=cash_id,
        entity_number=ref,
        details=f"reason={reason}; {old:.2f} -> {new:.2f}; delta={new - old:+.2f}",
    ))
    return (old, new)
```

- [ ] **Step 4: Test pass bo'lishini tekshirish**

Run: `python -m pytest tests/test_cash_recompute.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/finance_service.py tests/test_cash_recompute.py
git commit -m "feat(cash): recompute_cash_balance audit-yozadigan funksiya"
```

---

### Task 2: `previous_opening` ustun (ORM + ensure_column)

**Files:**
- Modify: `app/models/database.py` (CashBalanceDocItem, ~608-qator — `previous_balance` yonida)
- Modify: `app/models/database.py` yoki migratsiya joyi (ensure_*_column — `previous_balance` ustuni qayerda ensure qilingan bo'lsa shu yerda)

- [ ] **Step 1: ORM ustunini qo'shish**

`CashBalanceDocItem` modelida `previous_balance` qatoridan keyin:
```python
    previous_opening = Column(Float, default=None)  # Confirm vaqtidagi opening_balance (revert uchun)
```

- [ ] **Step 2: ensure_*_column migratsiya joyini topish**

Run: `grep -rn "cash_balance_doc_items\|previous_balance" app/models/database.py app/main.py app/*.py | grep -i "ALTER\|ensure\|ADD COLUMN"`

`previous_balance` (yoki shu jadval) uchun `ensure_*_column` chaqiruvi qayerda bo'lsa, yonига qo'shing. Agar `cash_balance_doc_items` uchun maxsus ensure funksiyasi bo'lmasa, mavjud umumiy migratsiya pattern (ALTER TABLE ... ADD COLUMN ... IF NOT EXISTS mantiq) bilan:
```python
# previous_opening ustuni (kassa hujjati revert opening-restore uchun)
_ensure_column(conn, "cash_balance_doc_items", "previous_opening", "FLOAT")
```
(Loyihadagi mavjud ensure helper nomi/signaturasiga moslang — `app/models/database.py` ichidagi boshqa `ensure` chaqiruvlarini namuna qiling. **Pending tranzaksiya orasida chaqirmang** — schema migration pattern.)

- [ ] **Step 3: Migratsiya ishlashini tekshirish**

Run: `python -c "import os; os.environ.setdefault('SECRET_KEY','x'); from app.models.database import engine; from sqlalchemy import inspect; print([c['name'] for c in inspect(engine).get_columns('cash_balance_doc_items')])"`
Expected: ro'yxatda `previous_opening` bor.

- [ ] **Step 4: Commit**

```bash
git add app/models/database.py
git commit -m "feat(cash): CashBalanceDocItem.previous_opening ustun (revert opening-restore)"
```

---

### Task 3: Kassa hujjati confirm/revert — opening-restore

**Files:**
- Modify: `app/routes/qoldiqlar.py` (confirm ~388-410, revert ~413-436)

- [ ] **Step 1: Confirm blokini o'zgartirish**

`qoldiqlar.py` confirm (taxminan 395-407). Mavjud:
```python
    from app.services.finance_service import cash_balance_formula as _cash_balance_formula
    for item in doc.items:
        cash = db.query(CashRegister).filter(CashRegister.id == item.cash_register_id).first()
        if cash:
            item.previous_balance = cash.balance
            current_balance, income_sum, expense_sum = _cash_balance_formula(db, cash.id)
            delta = float(item.balance or 0)
            target = current_balance + delta
            cash.opening_balance = target - income_sum + expense_sum
            cash.balance = target
    db.commit()
```
Yangi:
```python
    from app.services.finance_service import recompute_cash_balance
    for item in doc.items:
        cash = db.query(CashRegister).filter(CashRegister.id == item.cash_register_id).first()
        if cash:
            item.previous_balance = cash.balance                  # display (o'zgarmaydi)
            item.previous_opening = float(cash.opening_balance or 0)  # revert uchun
            delta = float(item.balance or 0)
            cash.opening_balance = float(cash.opening_balance or 0) + delta
            recompute_cash_balance(db, cash.id, reason="qoldiq_doc_confirm",
                                   ref=doc.number, actor=getattr(current_user, "username", None))
    db.commit()
```

- [ ] **Step 2: Revert blokini o'zgartirish**

Mavjud (taxminan 425-435):
```python
    from app.services.finance_service import cash_balance_formula as _cash_balance_formula
    for item in doc.items:
        cash = db.query(CashRegister).filter(CashRegister.id == item.cash_register_id).first()
        if cash and item.previous_balance is not None:
            current_balance, income_sum, expense_sum = _cash_balance_formula(db, cash.id)
            target = float(item.previous_balance)
            cash.opening_balance = target - income_sum + expense_sum
            cash.balance = target
    doc.status = "draft"
    db.commit()
```
Yangi (opening-restore, eski hujjatlar uchun fallback):
```python
    from app.services.finance_service import recompute_cash_balance, cash_balance_formula as _cash_balance_formula
    for item in doc.items:
        cash = db.query(CashRegister).filter(CashRegister.id == item.cash_register_id).first()
        if not cash:
            continue
        if item.previous_opening is not None:
            cash.opening_balance = float(item.previous_opening)
            recompute_cash_balance(db, cash.id, reason="qoldiq_doc_revert",
                                   ref=doc.number, actor=getattr(current_user, "username", None))
        elif item.previous_balance is not None:
            # Eski hujjat (previous_opening yo'q) — orqaga moslik
            current_balance, income_sum, expense_sum = _cash_balance_formula(db, cash.id)
            target = float(item.previous_balance)
            cash.opening_balance = target - income_sum + expense_sum
            cash.balance = target
    doc.status = "draft"
    db.commit()
```

- [ ] **Step 3: Regression test yozish (asosiy bug)**

`tests/test_cash_recompute.py` ga qo'shish — opening-restore income churn'dan keyin aniq:
```python
from app.models.database import Payment
from app.services.finance_service import cash_balance_formula


def test_doc_revert_exact_after_income_churn():
    """Confirm -> orasiga income -> revert: opening confirm-oldi qiymatiga aniq qaytishi."""
    db = _fresh_db()
    try:
        c = CashRegister(name="K", opening_balance=500.0, balance=500.0, currency="UZS")
        db.add(c); db.flush()
        opening_before = float(c.opening_balance)

        # Hujjat simulyatsiyasi: confirm delta=+200
        prev_opening = float(c.opening_balance or 0)
        c.opening_balance = prev_opening + 200.0
        from app.services.finance_service import recompute_cash_balance
        recompute_cash_balance(db, c.id, reason="t_confirm")
        db.flush()
        assert c.balance == 700.0

        # Orasiga income +300 (orqaga sanali to'lov)
        db.add(Payment(cash_register_id=c.id, type="income", amount=300.0, status="confirmed"))
        db.flush()
        recompute_cash_balance(db, c.id, reason="t_sync")
        assert c.balance == 1000.0   # 700 + 300

        # Revert: opening aniq tiklash
        c.opening_balance = prev_opening
        recompute_cash_balance(db, c.id, reason="t_revert")
        db.flush()
        assert c.opening_balance == opening_before        # 500.0 aniq
        assert c.balance == 800.0                          # opening 500 + income 300 (churn drift YO'Q)
    finally:
        db.rollback(); db.close()
```

- [ ] **Step 4: Testlar pass**

Run: `python -m pytest tests/test_cash_recompute.py -v`
Expected: 2 passed

- [ ] **Step 5: Sintaksis tekshiruv**

Run: `python -c "import ast; ast.parse(open(r'app/routes/qoldiqlar.py',encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add app/routes/qoldiqlar.py tests/test_cash_recompute.py
git commit -m "fix(cash): qoldiq hujjati confirm/revert opening-restore (snapshot drift fix)"
```

---

### Task 4: Drift monitorga kassa qo'shish

**Files:**
- Modify: `scripts/recompute_drift_monitor.py`

- [ ] **Step 1: Joriy strukturani o'qish**

`scripts/recompute_drift_monitor.py` ni o'qing — partner va stock drift bloklari qanday qurilganini (formula vs stored solishtirish, drift ro'yxati, Telegram alert format) tushuning.

- [ ] **Step 2: Kassa drift bloki qo'shish**

Partner/stock bloklari yoniga, import:
```python
from app.models.database import CashRegister
from app.services.finance_service import cash_balance_formula
```
Drift tekshiruvi (mavjud drift ro'yxati / alert pattern'ga moslang):
```python
    cash_drift = []
    for c in db.query(CashRegister).all():
        stored = float(c.balance or 0)
        computed, _, _ = cash_balance_formula(db, c.id)
        if abs(stored - computed) > 1.0:
            cash_drift.append((c.id, c.name, stored, computed, computed - stored))
```
Alert matniga kassa bo'limini qo'shing (partner/stock formatiga mos), `--quiet` rejimida faqat drift bo'lsa xabar.

- [ ] **Step 3: Quruq ishga tushirish (drift 0 kutiladi)**

Run: `python scripts/recompute_drift_monitor.py` (yoki mavjud entrypoint)
Expected: kassa drift = 0, xato yo'q.

- [ ] **Step 4: Commit**

```bash
git add scripts/recompute_drift_monitor.py
git commit -m "feat(monitor): drift monitorga kassa balans tekshiruvi"
```

---

### Task 5: Verify skript (C:\tools\check_cash_drift.py)

**Files:**
- Create: `C:\tools\check_cash_drift.py` (git'siz, tools papkasi)

- [ ] **Step 1: Skript yozish**

```python
"""Kassa drift tekshiruvi: stored balance vs cash_balance_formula.
Default DRY-RUN. --apply bilan recompute_cash_balance(reason='manual_drift_fix') (backup oling!)."""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")
from app.models.database import SessionLocal, CashRegister
from app.services.finance_service import cash_balance_formula, recompute_cash_balance

APPLY = "--apply" in sys.argv
db = SessionLocal()
try:
    drift = []
    for c in db.query(CashRegister).all():
        stored = float(c.balance or 0)
        computed, _, _ = cash_balance_formula(db, c.id)
        d = computed - stored
        flag = "DRIFT" if abs(d) > 1.0 else "ok"
        print(f"  [{flag}] {c.name:<28} stored={stored:>16,.2f}  formula={computed:>16,.2f}  delta={d:>+14,.2f}")
        if abs(d) > 1.0:
            drift.append(c.id)
    print(f"\nJami kassa: {db.query(CashRegister).count()} | drift: {len(drift)}")
    if APPLY and drift:
        for cid in drift:
            recompute_cash_balance(db, cid, reason="manual_drift_fix", actor="check_cash_drift")
        db.commit()
        print(f"[APPLIED] {len(drift)} kassa recompute qilindi.")
    else:
        print("[DRY-RUN] Hech narsa yozilmadi." if not APPLY else "[OK] Drift yo'q.")
finally:
    db.close()
```

- [ ] **Step 2: Quruq ishga tushirish**

Run: `python C:\tools\check_cash_drift.py`
Expected: har kassa `[ok]`, drift = 0.

---

### Task 6: Deploy (tungi oyna yoki tasdiqdan keyin)

**Files:** —

- [ ] **Step 1: To'liq test suite**

Run: `python -m pytest tests/test_cash_recompute.py -v`
Expected: barchasi pass.

- [ ] **Step 2: DB backup**

```powershell
Copy-Item "\\server2220\d\TOTLI BI\totli_holva.db" "\\server2220\d\TOTLI BI\totli_holva.db.bak_pre_cash_recompute_20260603"
```

- [ ] **Step 3: Smoke (sintaksis + import)**

Run: `python -c "import os; os.environ.setdefault('SECRET_KEY','x'); import app.main; print('import OK')"`
Expected: import OK

- [ ] **Step 4: Server restart (DCOM ELYOR→server2220 yoki schtasks)**

`schtasks /run /S server2220 /TN "TOTLI_BI_Server"` (yoki mavjud restart yo'li); `http://server2220:8080/login` → HTTP 200 kutish.

- [ ] **Step 5: Post-deploy verify**

Run: `python C:\tools\check_cash_drift.py`
Expected: drift = 0.

- [ ] **Step 6: Merge + push (backup bilan)**

```bash
git checkout main && git branch -f main feat-cash-recompute && git push origin main
```
(yoki loyihaning mavjud merge yo'li.)
