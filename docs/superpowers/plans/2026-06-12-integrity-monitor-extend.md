# DB Integrity Monitor — 5 yangi tekshiruv Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/integrity_check.py`'ga 5 yangi read-only tekshiruv qo'shish (subtotal desync, noto'g'ri ombor, price_type NULL, partner balance drift, agent qarz desync) — bugungi buglar kelajakda avtomatik Telegram'ga xabar berilsin.

**Architecture:** Mavjud `integrity_check.py` pattern: har tekshiruv `(count, message)` qaytaradi, `CHECKS` ro'yxatida, muammo bo'lsa Telegram. #1-3 va #5 sqlite3 cursor (tez, mavjud pattern). #4 (partner balance) ORM `compute_partner_balance` orqali (USD konversiya tufayli) — lazy import + SessionLocal.

**Tech Stack:** Python 3.12, sqlite3 (standalone), SQLAlchemy (faqat #4), pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-integrity-monitor-extend-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `scripts/integrity_check.py` | ✏️ 5 yangi funksiya + `CHECKS` ro'yxatiga 5 qator |
| `tests/test_integrity_checks.py` | 🆕 5 yangi tekshiruv testlari (in-memory sqlite + ORM) |

**Eslatma:** `integrity_check.py` mavjud — faqat funksiya QO'SHAMIZ (mavjud 9 ni
tegmaymiz). Yangi funksiyalar mavjud `check_*` pattern'iga mos.

---

## Task 1: Test helper — in-memory sqlite minimal sxema

sqlite3 tekshiruvlarini (#1-3, #5) sinash uchun minimal jadval sxemali in-memory
DB yaratuvchi helper.

**Files:**
- Create: `tests/test_integrity_checks.py`

- [ ] **Step 1: Helper + birinchi failing test yozish**

```python
"""integrity_check.py yangi tekshiruvlari testi."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import integrity_check as ic


def _mem_db():
    """Minimal sxemali in-memory sqlite (sotuv tekshiruvlari uchun)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript('''
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY, number TEXT, type TEXT, status TEXT,
            partner_id INTEGER, warehouse_id INTEGER, price_type_id INTEGER,
            source TEXT, subtotal REAL, total REAL, paid REAL, debt REAL,
            discount_percent REAL DEFAULT 0, discount_amount REAL DEFAULT 0
        );
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
            warehouse_id INTEGER, quantity REAL, price REAL, total REAL
        );
    ''')
    return conn


def test_subtotal_desync_detects_mismatch():
    conn = _mem_db()
    cur = conn.cursor()
    # subtotal=300 lekin items=600 (desync)
    cur.execute("INSERT INTO orders (id,type,status,subtotal,total) VALUES (1,'sale','completed',300,300)")
    cur.execute("INSERT INTO order_items (order_id,quantity,price,total) VALUES (1,1,300,300)")
    cur.execute("INSERT INTO order_items (order_id,quantity,price,total) VALUES (1,1,300,300)")
    count, msg = ic.check_subtotal_desync(cur)
    assert count == 1, f"1 desync kutilgan, topildi {count}"
    assert msg and "subtotal" in msg.lower()


def test_subtotal_desync_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,subtotal,total) VALUES (1,'sale','completed',600,600)")
    cur.execute("INSERT INTO order_items (order_id,quantity,price,total) VALUES (1,1,600,600)")
    count, msg = ic.check_subtotal_desync(cur)
    assert count == 0 and msg is None
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_integrity_checks.py::test_subtotal_desync_detects_mismatch -v`
Expected: FAIL — `AttributeError: module 'scripts.integrity_check' has no attribute 'check_subtotal_desync'`

- [ ] **Step 3: `check_subtotal_desync` funksiyasini qo'shish**

`scripts/integrity_check.py`'da, `check_negative_stock` dan KEYIN (boshqa
funksiyalar yonida), qo'shing:

```python
def check_subtotal_desync(cur) -> tuple[int, str | None]:
    """Order.subtotal != Σ(OrderItem.quantity × price) — subtotal desync.

    Chegirma subtotal'ni o'zgartirmaydi, shuning uchun qty×price bilan
    solishtiramiz (total emas). cancelled/draft chiqarib tashlanadi.
    """
    cur.execute("""
        SELECT o.id, o.number, o.subtotal,
               COALESCE((SELECT SUM(oi.quantity * oi.price) FROM order_items oi
                         WHERE oi.order_id = o.id), 0) AS items_sum
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
    """)
    bad = []
    for r in cur.fetchall():
        if abs(float(r[2] or 0) - float(r[3] or 0)) > 1.0:
            bad.append(r)
    if not bad:
        return 0, None
    msg = f"❌ <b>Subtotal desync</b>: {len(bad)} ta\n"
    for r in bad[:5]:
        msg += f"  #{r[0]} {r[1] or ''} subtotal={float(r[2] or 0):,.0f} items={float(r[3] or 0):,.0f} farq={float(r[2] or 0)-float(r[3] or 0):+,.0f}\n"
    if len(bad) > 5:
        msg += f"  ...va yana {len(bad) - 5} ta\n"
    return len(bad), msg
```

- [ ] **Step 4: Run tests, confirm PASS**

Run: `python -m pytest tests/test_integrity_checks.py -v`
Expected: 2 test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/integrity_check.py tests/test_integrity_checks.py
git commit -m "feat(integrity): subtotal desync tekshiruvi + test helper"
```

---

## Task 2: `check_sale_from_wrong_warehouse`

**Files:**
- Modify: `scripts/integrity_check.py`
- Test: `tests/test_integrity_checks.py`

- [ ] **Step 1: Failing test qo'shish**

`tests/test_integrity_checks.py` oxiriga:

```python
def test_wrong_warehouse_detects():
    conn = _mem_db()
    cur = conn.cursor()
    # Vozvrat (wh=7) ombordan sotuv — noto'g'ri
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (1,'sale','delivered',7)")
    # Xom ashyo (wh=1) — noto'g'ri
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (2,'sale','completed',1)")
    # To'g'ri (Do'kon 2 = wh=5)
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (3,'sale','completed',5)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 2, f"2 noto'g'ri kutilgan, topildi {count}"


def test_wrong_warehouse_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (1,'sale','completed',5)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 0 and msg is None
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_integrity_checks.py::test_wrong_warehouse_detects -v`
Expected: FAIL — `has no attribute 'check_sale_from_wrong_warehouse'`

- [ ] **Step 3: Funksiya qo'shish**

```python
def check_sale_from_wrong_warehouse(cur) -> tuple[int, str | None]:
    """Sotuv Vozvrat (wh=7) yoki Xom ashyo (wh=1) ombordan bo'lmasligi kerak.

    Order.warehouse_id yoki biror OrderItem.warehouse_id shu omborlarda bo'lsa.
    """
    cur.execute("""
        SELECT DISTINCT o.id, o.number, o.warehouse_id
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
          AND (
            o.warehouse_id IN (1, 7)
            OR EXISTS (SELECT 1 FROM order_items oi
                       WHERE oi.order_id = o.id AND oi.warehouse_id IN (1, 7))
          )
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"❌ <b>Noto'g'ri ombordan sotuv</b> (Vozvrat/Xom ashyo): {len(rows)} ta\n"
    for r in rows[:5]:
        msg += f"  #{r[0]} {r[1] or ''} wh={r[2]}\n"
    return len(rows), msg
```

- [ ] **Step 4: Run tests, confirm PASS**

Run: `python -m pytest tests/test_integrity_checks.py -v`
Expected: 4 test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/integrity_check.py tests/test_integrity_checks.py
git commit -m "feat(integrity): noto'g'ri ombordan sotuv tekshiruvi"
```

---

## Task 3: `check_null_price_type`

**Files:**
- Modify: `scripts/integrity_check.py`
- Test: `tests/test_integrity_checks.py`

- [ ] **Step 1: Failing test qo'shish**

```python
def test_null_price_type_detects():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (1,'sale','completed',NULL)")
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (2,'sale','delivered',4)")
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (3,'sale','draft',NULL)")  # draft chiqadi
    count, msg = ic.check_null_price_type(cur)
    assert count == 1, f"1 NULL kutilgan, topildi {count}"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_integrity_checks.py::test_null_price_type_detects -v`
Expected: FAIL — `has no attribute 'check_null_price_type'`

- [ ] **Step 3: Funksiya qo'shish**

```python
def check_null_price_type(cur) -> tuple[int, str | None]:
    """Aktiv sotuvda price_type_id NULL bo'lmasligi kerak (narx turi tanlanmagan)."""
    cur.execute("""
        SELECT o.id, o.number, o.source
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
          AND o.price_type_id IS NULL
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"⚠️ <b>Narx turi (price_type) NULL</b>: {len(rows)} ta aktiv sotuv\n"
    for r in rows[:5]:
        msg += f"  #{r[0]} {r[1] or ''} source={r[2] or '?'}\n"
    if len(rows) > 5:
        msg += f"  ...va yana {len(rows) - 5} ta\n"
    return len(rows), msg
```

- [ ] **Step 4: Run tests, confirm PASS**

Run: `python -m pytest tests/test_integrity_checks.py -v`
Expected: 5 test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/integrity_check.py tests/test_integrity_checks.py
git commit -m "feat(integrity): price_type NULL tekshiruvi"
```

---

## Task 4: `check_agent_debt_desync`

Agent qarz invarianti: aktiv sotuvda `debt == max(0, total − paid)`. Buzilsa,
per-order qarz ko'rsatkichi noizchil (bugungi 06-03 turi).

**Files:**
- Modify: `scripts/integrity_check.py`
- Test: `tests/test_integrity_checks.py`

- [ ] **Step 1: Failing test qo'shish**

```python
def test_agent_debt_desync_detects():
    conn = _mem_db()
    cur = conn.cursor()
    # debt=0 lekin total=1000, paid=0 → kutilgan debt=1000 (desync)
    cur.execute("INSERT INTO orders (id,type,status,source,total,paid,debt) VALUES (1,'sale','delivered','agent',1000,0,0)")
    # to'g'ri: debt=max(0,800-300)=500
    cur.execute("INSERT INTO orders (id,type,status,source,total,paid,debt) VALUES (2,'sale','delivered','agent',800,300,500)")
    count, msg = ic.check_agent_debt_desync(cur)
    assert count == 1, f"1 desync kutilgan, topildi {count}"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_integrity_checks.py::test_agent_debt_desync_detects -v`
Expected: FAIL — `has no attribute 'check_agent_debt_desync'`

- [ ] **Step 3: Funksiya qo'shish**

```python
def check_agent_debt_desync(cur) -> tuple[int, str | None]:
    """Aktiv sotuvda Order.debt == max(0, total − paid) bo'lishi kerak.

    Agent/oddiy sotuvlarda per-order qarz ko'rsatkichi izchilligi.
    """
    cur.execute("""
        SELECT o.id, o.number, o.source, o.total, o.paid, o.debt
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
    """)
    bad = []
    for r in cur.fetchall():
        total, paid, debt = float(r[3] or 0), float(r[4] or 0), float(r[5] or 0)
        expected = max(0.0, total - paid)
        if abs(debt - expected) > 1.0:
            bad.append((r[0], r[1], r[2], total, paid, debt, expected))
    if not bad:
        return 0, None
    msg = f"⚠️ <b>Qarz desync</b> (debt ≠ total−paid): {len(bad)} ta\n"
    for b in bad[:5]:
        msg += f"  #{b[0]} {b[1] or ''} total={b[3]:,.0f} paid={b[4]:,.0f} debt={b[5]:,.0f} kutilgan={b[6]:,.0f}\n"
    if len(bad) > 5:
        msg += f"  ...va yana {len(bad) - 5} ta\n"
    return len(bad), msg
```

- [ ] **Step 4: Run tests, confirm PASS**

Run: `python -m pytest tests/test_integrity_checks.py -v`
Expected: 6 test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/integrity_check.py tests/test_integrity_checks.py
git commit -m "feat(integrity): agent qarz desync tekshiruvi"
```

---

## Task 5: `check_partner_balance_drift` (ORM)

USD konversiya tufayli `compute_partner_balance` (ORM) ishlatamiz. Bu yagona
tekshiruv `cur` (sqlite3) emas, alohida ORM session oladi.

**Files:**
- Modify: `scripts/integrity_check.py`
- Test: `tests/test_integrity_checks.py`

- [ ] **Step 1: Failing test (ORM, conftest fixtures) qo'shish**

`tests/test_integrity_checks.py` oxiriga:

```python
def test_partner_balance_drift_detects(db, sample_partner):
    # Partner.balance ataylab noto'g'ri (drift)
    sample_partner.balance = 999999
    db.add(sample_partner); db.commit()
    count, msg = ic.check_partner_balance_drift_orm(db)
    assert count >= 1, f"drift kutilgan, topildi {count}"
    assert msg and "balans" in msg.lower()


def test_partner_balance_drift_clean(db, sample_partner):
    # compute_partner_balance bilan to'g'ri set
    from app.services.partner_balance_service import compute_partner_balance
    sample_partner.balance = compute_partner_balance(db, sample_partner.id)
    db.add(sample_partner); db.commit()
    count, msg = ic.check_partner_balance_drift_orm(db)
    assert count == 0
```

> **Eslatma:** `db` va `sample_partner` — mavjud `tests/conftest.py` fixtures
> (in-memory ORM). Bu test ORM ishlatadi (boshqalar sqlite3).

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_integrity_checks.py::test_partner_balance_drift_detects -v`
Expected: FAIL — `has no attribute 'check_partner_balance_drift_orm'`

- [ ] **Step 3: ORM funksiya qo'shish**

`scripts/integrity_check.py`'da, ORM versiya (cursor emas, session oladi):

```python
def check_partner_balance_drift_orm(db) -> tuple[int, str | None]:
    """Partner.balance != compute_partner_balance(hujjatlar) — drift.

    USD konversiya tufayli ORM (compute_partner_balance) ishlatadi.
    `db` — SQLAlchemy Session.
    """
    from app.models.database import Partner
    from app.services.partner_balance_service import compute_partner_balance
    bad = []
    for p in db.query(Partner).filter(Partner.is_active == True):
        try:
            computed = compute_partner_balance(db, p.id)
        except Exception:
            continue
        stored = float(p.balance or 0)
        if abs(stored - computed) > 1.0:
            bad.append((p.id, p.name, stored, computed))
    if not bad:
        return 0, None
    bad.sort(key=lambda x: -abs(x[2] - x[3]))
    msg = f"❌ <b>Partner balans drift</b>: {len(bad)} ta\n"
    for b in bad[:5]:
        msg += f"  #{b[0]} {(b[1] or '')[:20]} balans={b[2]:,.0f} hisob={b[3]:,.0f} farq={b[2]-b[3]:+,.0f}\n"
    if len(bad) > 5:
        msg += f"  ...va yana {len(bad) - 5} ta\n"
    return len(bad), msg
```

- [ ] **Step 4: Run tests, confirm PASS**

Run: `python -m pytest tests/test_integrity_checks.py -v`
Expected: 8 test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/integrity_check.py tests/test_integrity_checks.py
git commit -m "feat(integrity): partner balans drift tekshiruvi (ORM)"
```

---

## Task 6: CHECKS ro'yxatiga ulash + ORM integratsiya + Task Scheduler

sqlite3 tekshiruvlar (#1-4) `CHECKS` ro'yxatiga; ORM tekshiruv (#5) `main()` da
alohida chaqiriladi (cursor emas, session).

**Files:**
- Modify: `scripts/integrity_check.py`

- [ ] **Step 1: 4 sqlite3 tekshiruvni CHECKS ro'yxatiga qo'shish**

`scripts/integrity_check.py`'da `CHECKS` ro'yxati oxiriga (mavjud 9 dan keyin):

```python
    ("Subtotal desync (subtotal vs items)", check_subtotal_desync),
    ("Noto'g'ri ombordan sotuv", check_sale_from_wrong_warehouse),
    ("Narx turi (price_type) NULL", check_null_price_type),
    ("Qarz desync (debt vs total-paid)", check_agent_debt_desync),
```

- [ ] **Step 2: ORM tekshiruvni main()'ga ulash**

`main()` funksiyasida, `conn.close()` dan KEYIN (sqlite3 tekshiruvlar tugagach),
ORM partner balance tekshiruvini qo'shing:

```python
    # ORM tekshiruv (partner balance — USD konversiya tufayli ORM kerak)
    try:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        from app.models.database import SessionLocal
        _db = SessionLocal()
        try:
            pcount, pmsg = check_partner_balance_drift_orm(_db)
        finally:
            _db.close()
        total_count += pcount
        if pmsg:
            issues.append(pmsg)
            summary.append(f"❌ Partner balans drift: {pcount}")
        else:
            summary.append("✅ Partner balans drift")
    except Exception as e:
        log(f"Partner balance check xato: {e}")
        summary.append(f"⚠️ Partner balans drift: ERROR ({e})")
```

> Aniq joy: `main()`'da `conn.close()` qatoridan keyin, `now = datetime.now()...`
> dan oldin. `os` allaqachon import qilingan (fayl boshida).

- [ ] **Step 3: To'liq smoke — real DB'da false positive yo'qligini tekshirish**

Run: `python scripts/integrity_check.py --verbose`
Expected: 14 tekshiruv summary; 5 yangi tekshiruv `✅` (bugungi buglar
tuzatilgan — toza DB). Agar biror yangi tekshiruv muammo topsa, uni qo'lda
tekshiring (haqiqiy drift bo'lishi mumkin).

- [ ] **Step 4: Test to'plami**

Run: `python -m pytest tests/test_integrity_checks.py -v`
Expected: 8 test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/integrity_check.py
git commit -m "feat(integrity): 5 yangi tekshiruvni CHECKS + main'ga ulash"
```

- [ ] **Step 6: Task Scheduler tekshirish (server2220)**

server2220'da integrity task ishlayotganini tekshiring:
```
schtasks /query /S server2220 /TN "TOTLI_Integrity" /V /FO LIST | findstr "Status Result Schedule"
```
- Agar task BOR va kunlik/soatlik → tugadi.
- Agar YO'Q yoki to'xtagan → qayta yaratish:
```
schtasks /create /S server2220 /TN "TOTLI_Integrity" /TR "powershell -ExecutionPolicy Bypass -File \"D:\TOTLI BI\scripts\_integrity_runner.ps1\"" /SC DAILY /ST 07:00 /RU SYSTEM /F
schtasks /run /S server2220 /TN "TOTLI_Integrity"
```
Keyin `integrity_check.log` (server2220) da natijani tasdiqlang.

---

## Self-Review (reja muallifi tomonidan bajarildi)

- **Spec qamrovi:** ✅ 5 tekshiruv (Task 1-5), CHECKS ulash (Task 6), Task
  Scheduler (Task 6 Step 6), read-only (barcha SELECT/ORM query), Telegram
  (mavjud `send_telegram`).
- **Placeholder skani:** Yo'q — har funksiya to'liq raw SQL/ORM kodi bilan.
- **Tip izchilligi:** `check_subtotal_desync`, `check_sale_from_wrong_warehouse`,
  `check_null_price_type`, `check_agent_debt_desync` (cursor → `(count, msg)`);
  `check_partner_balance_drift_orm` (session → `(count, msg)`) — nomlar barcha
  taskda bir xil. ORM versiya `_orm` suffiksi bilan ajratilgan (cursor olmaydi).
- **Test stillari:** #1-4 in-memory sqlite (`_mem_db`), #5 ORM (conftest `db`/
  `sample_partner`). Ataylab — sqlite3 tekshiruvlar standalone, ORM tekshiruv
  ORM fixtures.
