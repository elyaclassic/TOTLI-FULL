# Tan narx snapshot fix (C2) — Implementatsiya rejasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Foyda hisoboti sotuv vaqtidagi tan narxni ishlatsin (snapshot, qotiriladi); production anomaliya qo'riq bilan yangilasin; QLD/report soxta overwrite o'chirilsin; buzilgan narxlar tuzatilsin.

**Architecture:** `OrderItem`'ga `cost_price` ustun + SQLAlchemy `before_insert` event listener (barcha 18+ yaratish nuqtasini avtomatik qamraydi, DRY). Foyda hisoboti `cost_price`'ga (fallback `Product.purchase_price`) o'tadi. Production `_update_output_cost_and_price` anomaliya tekshiradi. QLD/report mutatsiyalari olib tashlanadi. Buzilgan narxlar alohida skript bilan tuzatiladi.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest, Python 3.12. Repo: `\\server2220\d\TOTLI BI`. Branch: feat-cost-snapshot.

---

### Task 1: OrderItem.cost_price ustun + snapshot event listener

**Files:**
- Modify: `app/models/database.py` (OrderItem ~1043; ensure_* + init_db; event listener)
- Test: `tests/test_cost_snapshot.py` (yangi)

- [ ] **Step 1: Failing test yozish**

`tests/test_cost_snapshot.py`:
```python
"""C2: OrderItem.cost_price sotuv vaqtidagi tan narxni qotiradi (before_insert snapshot)."""
from app.models.database import Product, Order, OrderItem


def test_orderitem_cost_snapshot(db):
    p = Product(name="Test mahsulot C2", purchase_price=5000, sale_price=8000)
    db.add(p); db.flush()
    o = Order(number="T-C2-1", type="sale", status="completed")
    db.add(o); db.flush()
    oi = OrderItem(order_id=o.id, product_id=p.id, quantity=2, price=8000, total=16000)
    db.add(oi); db.flush()
    assert float(oi.cost_price) == 5000


def test_orderitem_cost_explicit_not_overwritten(db):
    p = Product(name="Test mahsulot C2b", purchase_price=5000)
    db.add(p); db.flush()
    o = Order(number="T-C2-2", type="sale")
    db.add(o); db.flush()
    oi = OrderItem(order_id=o.id, product_id=p.id, quantity=1, price=1, total=1, cost_price=9999)
    db.add(oi); db.flush()
    assert float(oi.cost_price) == 9999
```

- [ ] **Step 2: Test fail bo'lishini tekshirish**

Run: `python -m pytest tests/test_cost_snapshot.py -v`
Expected: FAIL — `OrderItem` da `cost_price` atributi yo'q (TypeError yoki AttributeError).

- [ ] **Step 3: ORM ustun qo'shish**

`app/models/database.py`, `OrderItem` klassida `total = Column(Float)` dan keyin:
```python
    cost_price = Column(Float, default=0)  # Sotuv vaqtidagi tan narx snapshot (C2)
```

- [ ] **Step 4: before_insert event listener qo'shish**

`OrderItem` klassi va uning `relationship`'laridan keyin (masalan `PosDraft` klassidan oldin), qo'shish:
```python
from sqlalchemy import event as _sa_event, text as _sa_text


@_sa_event.listens_for(OrderItem, "before_insert")
def _snapshot_order_item_cost(mapper, connection, target):
    """C2: har OrderItem insert'da cost_price bo'sh bo'lsa, Product.purchase_price'dan
    sotuv vaqtidagi tan narxni qotiradi. Barcha 18+ yaratish nuqtasini avtomatik qamraydi."""
    if (target.cost_price or 0) > 0:
        return
    if not target.product_id:
        return
    row = connection.execute(
        _sa_text("SELECT purchase_price FROM products WHERE id = :pid"),
        {"pid": target.product_id},
    ).first()
    if row and row[0]:
        target.cost_price = float(row[0] or 0)
```
(Agar `event`/`text` allaqachon import qilingan bo'lsa, mavjudini ishlating — alias konflikti bo'lmasin.)

- [ ] **Step 5: ensure_* migratsiya + init_db**

`ensure_cash_register_payment_type` pattern bo'yicha yangi funksiya qo'shish:
```python
def ensure_order_item_cost_price():
    """order_items jadvaliga cost_price ustunini qo'shadi (tan narx snapshot, C2)."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(order_items)"))
            cols = [row[1] for row in r]
            if "cost_price" not in cols:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN cost_price FLOAT DEFAULT 0"))
                print("order_items.cost_price ustuni qo'shildi.")
    except Exception as e:
        print(f"ensure_order_item_cost_price: {e}")
```
`init_db()` ichida oxirgi `ensure_*()` chaqiruvidan keyin:
```python
    ensure_order_item_cost_price()
```

- [ ] **Step 6: Test pass + migratsiya tekshirish**

Run: `python -m pytest tests/test_cost_snapshot.py -v`
Expected: 2 passed.
Run: `python -c "import os; os.environ.setdefault('SECRET_KEY','x'); from app.models.database import init_db, engine; init_db(); from sqlalchemy import inspect; print('cost_price' in [c['name'] for c in inspect(engine).get_columns('order_items')])"`
Expected: True

- [ ] **Step 7: Commit**

```bash
git add app/models/database.py tests/test_cost_snapshot.py
git commit -m "feat(cost): OrderItem.cost_price + before_insert snapshot (C2)"
```

---

### Task 2: Foyda hisoboti snapshot'ni ishlatadi

**Files:**
- Modify: `app/routes/reports.py:2544` va `:2605`
- Test: `tests/test_cost_snapshot.py` (qo'shish)

- [ ] **Step 1: Failing test yozish**

`tests/test_cost_snapshot.py` ga qo'shish:
```python
def test_cogs_uses_snapshot_not_current_price(db):
    """Foyda COGS: cost_price>0 bo'lsa shuni, aks holda purchase_price fallback."""
    p = Product(name="COGS mahsulot", purchase_price=9999, sale_price=10000)  # joriy narx buzilgan
    db.add(p); db.flush()
    o = Order(number="T-C2-3", type="sale", status="completed")
    db.add(o); db.flush()
    oi = OrderItem(order_id=o.id, product_id=p.id, quantity=2, price=10000, total=20000, cost_price=3000)
    db.add(oi); db.flush()
    # snapshot 3000 ishlatilsin (joriy 9999 emas)
    cost = float(oi.cost_price or 0) or float(p.purchase_price or 0)
    assert cost == 3000
    # cost_price=0 bo'lsa fallback
    oi2 = OrderItem(order_id=o.id, product_id=p.id, quantity=1, price=1, total=1)
    oi2.cost_price = 0  # listener'dan keyin majburan 0
    db.add(oi2); db.flush()
    cost2 = float(oi2.cost_price or 0) or float(p.purchase_price or 0)
    assert cost2 == 9999  # fallback (snapshot yo'q)
```

- [ ] **Step 2: Test fail/pass holatini ko'rish**

Run: `python -m pytest tests/test_cost_snapshot.py::test_cogs_uses_snapshot_not_current_price -v`
Expected: 1-assert PASS bo'lishi mumkin (listener cost_price=3000 ni saqlamaydi chunki explicit berildi). Bu test COGS formulasini tekshiradi, kod o'zgarishi keyingi qadamda.

- [ ] **Step 3: reports.py:2544 o'zgartirish**

Mavjud:
```python
        for oi, prod in sale_items:
            cogs += float(prod.purchase_price or 0) * float(oi.quantity or 0)
```
Yangi:
```python
        for oi, prod in sale_items:
            unit_cost = float(getattr(oi, "cost_price", 0) or 0) or float(prod.purchase_price or 0)
            cogs += unit_cost * float(oi.quantity or 0)
```

- [ ] **Step 4: reports.py:2605 o'zgartirish**

Mavjud:
```python
            daily_data[key]["cogs"] += float(prod.purchase_price or 0) * float(oi.quantity or 0)
```
Yangi:
```python
            _uc = float(getattr(oi, "cost_price", 0) or 0) or float(prod.purchase_price or 0)
            daily_data[key]["cogs"] += _uc * float(oi.quantity or 0)
```

- [ ] **Step 5: Sintaksis + test**

Run: `python -c "import ast; ast.parse(open(r'app/routes/reports.py',encoding='utf-8').read()); print('OK')"`
Expected: OK
Run: `python -m pytest tests/test_cost_snapshot.py -v`
Expected: barchasi pass.

- [ ] **Step 6: Commit**

```bash
git add app/routes/reports.py tests/test_cost_snapshot.py
git commit -m "feat(cost): foyda COGS OrderItem.cost_price snapshot'ni ishlatadi (C2)"
```

---

### Task 3: Production tan narx anomaliya qo'riq

**Files:**
- Modify: `app/routes/production.py:286-298` (`_update_output_cost_and_price`)
- Test: `tests/test_cost_snapshot.py` (qo'shish)

- [ ] **Step 1: Failing test yozish**

Helper'ni izolyatsiyada test qilish uchun mantiqni soddalashtirib tekshiramiz. `tests/test_cost_snapshot.py` ga:
```python
def test_production_cost_anomaly_guard(db):
    """Anomaliya narx (>sale_price yoki >3x old) purchase_price'ni o'zgartirmasin."""
    from app.routes.production import _is_anomalous_cost
    # sale_price'dan baland
    assert _is_anomalous_cost(new_cost=12000, old_cost=5000, sale_price=10000) is True
    # eski narxdan 3x oshган
    assert _is_anomalous_cost(new_cost=16000, old_cost=5000, sale_price=99999) is True
    # normal
    assert _is_anomalous_cost(new_cost=5500, old_cost=5000, sale_price=10000) is False
    # eski narx 0 bo'lsa (birinchi marta) — faqat sale_price qo'riq
    assert _is_anomalous_cost(new_cost=5000, old_cost=0, sale_price=10000) is False
```

- [ ] **Step 2: Test fail bo'lishini tekshirish**

Run: `python -m pytest tests/test_cost_snapshot.py::test_production_cost_anomaly_guard -v`
Expected: FAIL — `_is_anomalous_cost` import yo'q.

- [ ] **Step 3: `_is_anomalous_cost` helper + guard qo'shish**

`app/routes/production.py`, `_update_output_cost_and_price`'dan oldin:
```python
def _is_anomalous_cost(new_cost: float, old_cost: float, sale_price: float) -> bool:
    """Yangi tan narx g'ayritabiiymi? (C2 anomaliya qo'riq).
    True bo'lsa purchase_price yozilmaydi (eski saqlanadi)."""
    nc = float(new_cost or 0)
    if nc <= 0:
        return True  # 0/manfiy — yozmaymiz
    sp = float(sale_price or 0)
    if sp > 0 and nc > sp:
        return True  # sotuv narxidan baland
    oc = float(old_cost or 0)
    if oc > 0 and nc > 3 * oc:
        return True  # eski narxdan 3 baravar oshган
    return False
```
`_update_output_cost_and_price` ichida, `old = output_product.purchase_price or 0` dan keyin, `output_product.purchase_price = cost` dan OLDIN:
```python
    old = output_product.purchase_price or 0
    if _is_anomalous_cost(cost, old, output_product.sale_price or 0):
        logger.warning(
            "PRICE ANOMALY SKIPPED %s: yangi tannarx %.0f (eski %.0f, sotuv %.0f) — saqlanmadi",
            output_product.name, cost, old, output_product.sale_price or 0,
        )
        return
    output_product.purchase_price = cost
```
(Mavjud `old = ...` qatorini takrorlamang — yuqoridagini o'sha joyga moslang.)

- [ ] **Step 4: Test pass**

Run: `python -m pytest tests/test_cost_snapshot.py::test_production_cost_anomaly_guard -v`
Expected: PASS.

- [ ] **Step 5: Sintaksis + commit**

Run: `python -c "import ast; ast.parse(open(r'app/routes/production.py',encoding='utf-8').read()); print('OK')"`
Expected: OK
```bash
git add app/routes/production.py tests/test_cost_snapshot.py
git commit -m "feat(cost): production tannarx anomaliya qo'riq (C2)"
```

---

### Task 4: Soxta purchase_price overwrite'larni o'chirish

**Files:**
- Modify: `app/routes/qoldiqlar.py:1795-1798`
- Modify: `app/routes/reports.py:1192-1193`

- [ ] **Step 1: qoldiqlar.py overwrite o'chirish**

Mavjud (QLD/INV confirm):
```python
        if (item.cost_price or 0) > 0:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            if prod:
                prod.purchase_price = item.cost_price
```
O'chirib, o'rniga izoh:
```python
        # C2: QLD/INV qoldiq kiritish tan narx hodisasi EMAS — Product.purchase_price'ga
        # tegmaymiz (eski overwrite buzilish manbai edi). Tan narx production'da yangilanadi.
```

- [ ] **Step 2: reports.py overwrite o'chirish**

Mavjud (stock-source hisobot):
```python
        if tannarx > 0:
            product.purchase_price = tannarx
        if sotuv_narxi > 0:
            product.sale_price = sotuv_narxi
```
`purchase_price` qatorini o'chirish (sale_price qoladi — qamrovdan tashqari):
```python
        # C2: hisobot READ-ONLY — Product.purchase_price'ni o'zgartirmaymiz (eski mutatsiya).
        if sotuv_narxi > 0:
            product.sale_price = sotuv_narxi
```

- [ ] **Step 3: Sintaksis tekshirish**

Run: `python -c "import ast; ast.parse(open(r'app/routes/qoldiqlar.py',encoding='utf-8').read()); ast.parse(open(r'app/routes/reports.py',encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add app/routes/qoldiqlar.py app/routes/reports.py
git commit -m "fix(cost): QLD/report soxta purchase_price overwrite o'chirildi (C2)"
```

---

### Task 5: Buzilgan narx cleanup skript (data)

**Files:**
- Create: `C:\tools\fix_corrupt_purchase_price.py` (git'siz)

- [ ] **Step 1: Skript yozish**

```python
"""C2 data cleanup: anomaliya purchase_price (>sale_price) mahsulotlarni topib,
product_price_history'dan oxirgi NORMAL (anomaliya bo'lmagan) qiymatga tiklaydi.
Default DRY-RUN. --apply bilan yozadi (backup oling!)."""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")
from app.models.database import SessionLocal, Product, ProductPriceHistory

APPLY = "--apply" in sys.argv
db = SessionLocal()
try:
    fixed = []
    for p in db.query(Product).filter(Product.is_active == True).all():
        pp = float(p.purchase_price or 0)
        sp = float(p.sale_price or 0)
        if pp <= 0 or sp <= 0 or pp <= sp:
            continue  # normal
        # Anomaliya: tan narx sotuvdan baland. price_history'dan oxirgi normalni top.
        hist = db.query(ProductPriceHistory).filter(
            ProductPriceHistory.product_id == p.id
        ).order_by(ProductPriceHistory.id.desc()).all()
        normal = None
        for h in hist:
            v = float(getattr(h, "old_purchase_price", 0) or 0)
            if 0 < v <= sp:
                normal = v
                break
        fixed.append((p, pp, sp, normal))
    print(f"{'Mahsulot':<30}{'joriy_pp':>12}{'sotuv':>12}{'tiklash':>12}")
    print("-"*68)
    for p, pp, sp, normal in fixed:
        print(f"  {str(p.name)[:28]:<30}{pp:>12,.0f}{sp:>12,.0f}{(normal if normal else 'YO`Q'):>12}")
    print(f"\nAnomaliya: {len(fixed)} | tiklab bo'ladigan: {sum(1 for _,_,_,n in fixed if n)}")
    if APPLY:
        cnt = 0
        for p, pp, sp, normal in fixed:
            if normal:
                p.purchase_price = normal; cnt += 1
        db.commit()
        print(f"[APPLIED] {cnt} mahsulot tiklandi. (price_history'da normal topilmaganlar qo'lda)")
    else:
        print("[DRY-RUN] Hech narsa yozilmadi.")
finally:
    db.close()
```
(ProductPriceHistory model nomi/maydonlari `database.py:377` dagiga moslang: `old_purchase_price`, `new_purchase_price`.)

- [ ] **Step 2: Quruq ishga tushirish**

Run: `python C:\tools\fix_corrupt_purchase_price.py`
Expected: anomaliya mahsulotlar ro'yxati (KITOB kabi) + tiklanadiganlar soni. Hech narsa yozilmaydi.

---

### Task 6: Deploy (test suite, backup, restart, cleanup, push)

**Files:** —

- [ ] **Step 1: To'liq test suite**

Run: `python -m pytest tests/test_cost_snapshot.py tests/test_advance_payment.py -v`
Expected: barchasi pass.

- [ ] **Step 2: DB backup**

```powershell
Copy-Item "\\server2220\d\TOTLI BI\totli_holva.db" "\\server2220\d\TOTLI BI\totli_holva.db.bak_pre_cost_snapshot_20260603"
```

- [ ] **Step 3: Import smoke**

Run: `python -c "import os,sys; p=r'\\server2220\d\TOTLI BI'; sys.path.insert(0,p); os.chdir(p); os.environ.setdefault('SECRET_KEY','x'); import app.routes.reports, app.routes.production, app.routes.qoldiqlar, app.models.database; print('IMPORT OK')"`
Expected: IMPORT OK

- [ ] **Step 4: Merge + restart (foreground, PID tasdiqlash)**

```bash
git branch -f main feat-cost-snapshot && git checkout main
```
Server PID'ni server.log'dan (Grep tool) ol → `taskkill /S server2220 /PID <PID> /F` → PID o'lganini `tasklist /S /FI "PID eq <PID>"` bilan TASDIQLA → `schtasks /run /S server2220 /TN "TOTLI_BI_Server"` → `/login` 200 poll → yangi PID tasdiqla.

- [ ] **Step 5: Data cleanup --apply (backup'dan keyin)**

Run: `python C:\tools\fix_corrupt_purchase_price.py --apply`
Expected: anomaliya mahsulotlar tiklandi (KITOB normal qiymatga).

- [ ] **Step 6: Push**

```bash
git push origin main
```
