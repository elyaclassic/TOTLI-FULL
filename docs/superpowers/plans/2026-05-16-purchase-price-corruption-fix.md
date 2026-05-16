# purchase_price korruption fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ishlab chiqarish narx-rollup'idagi feedback rekursiyani o'ldirish (deterministik dona-narx + tarix + sanity-log) va 136 buzilgan mahsulotni retseptdan backfill qilish.

**Architecture:** Jonli yo'l (`_update_output_cost_and_price`) endi production allaqachon hisoblagan dona-boshiga `cost_per_unit`ni flat tayinlaydi (weighted-avg/self-feedback YO'Q) + `product_price_history` yozadi + sanity-log. Backfill skripti jonli batch bo'lmagani uchun statik `_calculate_recipe_cost_per_kg(recipe) × recipe_kg_per_unit(recipe)` (dona-boshiga) ishlatadi. In-place (A1), yangi servis moduli yo'q.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest (in-memory SQLite, `tests/conftest.py` `db` fixture).

**Spec:** `docs/superpowers/specs/2026-05-16-purchase-price-corruption-fix-design.md`

---

## File Structure

- **Modify:** `app/routes/production.py` — `_update_output_cost_and_price` (qayta yoziladi, signatura o'zgaradi), yangi `_log_price_history` helper, chaqiruvchi `:319`.
- **Create:** `scripts/backfill_produced_purchase_price.py` — bir martalik reconcile (dry-run/apply, idempotent).
- **Create:** `tests/test_production_cost.py` — forward-fix + backfill xulq-atvor testlari.

---

## Task 1: Forward-fix — `_log_price_history` + `_update_output_cost_and_price` qayta yozish

**Files:**
- Modify: `app/routes/production.py` (function `_update_output_cost_and_price` ~249-270; caller ~319)
- Test: `tests/test_production_cost.py`

- [ ] **Step 1: Write the failing test**

`tests/test_production_cost.py`:

```python
from datetime import datetime

from app.models.database import Product, Recipe, RecipeItem, Stock


def _mk_output(db, *, name="MAYDA PISTA 400gr", pp=999999, sale=20000):
    p = Product(name=name, code=name.replace(" ", "_"), type="tayyor",
                is_active=True, purchase_price=pp, sale_price=sale)
    db.add(p); db.flush()
    r = Recipe(product_id=p.id, name=name, output_quantity=1.0, is_active=True)
    db.add(r); db.flush()
    return p, r


def _mk_stock(db, *, wh_id, product_id, qty=10.0, cost=999999):
    s = Stock(warehouse_id=wh_id, product_id=product_id, quantity=qty, cost_price=cost)
    db.add(s); db.commit()
    return s


class _Prod:
    number = "PR-TEST-001"


def test_update_output_sets_pp_to_cost_per_unit_not_weighted(db):
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=999999)            # buzuq eski pp
    _mk_stock(db, wh_id=1, product_id=p.id, qty=10.0, cost=999999)
    _update_output_cost_and_price(db, 1, r, 15000.0, _Prod())
    db.refresh(p)
    assert p.purchase_price == 15000.0          # weighted-avg EMAS, flat = cost_per_unit


def test_update_output_idempotent(db):
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=999999)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0, _Prod())
    _update_output_cost_and_price(db, 1, r, 15000.0, _Prod())   # 2-marta
    db.refresh(p)
    assert p.purchase_price == 15000.0          # surilmaydi (feedback-rekursiya o'lgan)


def test_update_output_zero_cost_keeps_old(db):
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=12345)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 0.0, _Prod())
    db.refresh(p)
    assert p.purchase_price == 12345            # nolga tushmaydi


def test_update_output_writes_price_history(db):
    from app.routes.production import _update_output_cost_and_price
    from app.models.database import ProductPriceHistory
    p, r = _mk_output(db, pp=999999)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0, _Prod())
    rows = db.query(ProductPriceHistory).filter(ProductPriceHistory.product_id == p.id).all()
    assert len(rows) == 1
    assert rows[0].old_purchase_price == 999999.0
    assert rows[0].new_purchase_price == 15000.0
    assert rows[0].doc_number == "PR-TEST-001"


def test_update_output_no_history_when_unchanged(db):
    from app.routes.production import _update_output_cost_and_price
    from app.models.database import ProductPriceHistory
    p, r = _mk_output(db, pp=15000)             # allaqachon to'g'ri
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0, _Prod())
    assert db.query(ProductPriceHistory).filter(
        ProductPriceHistory.product_id == p.id).count() == 0


def test_update_output_anomaly_warns_but_completes(db, caplog):
    import logging
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=100, sale=10000)
    _mk_stock(db, wh_id=1, product_id=p.id)
    with caplog.at_level(logging.WARNING):
        _update_output_cost_and_price(db, 1, r, 50000.0, _Prod())   # cost > sale
    db.refresh(p)
    assert p.purchase_price == 50000.0          # baribir yoziladi (bloklamaydi)
    assert any("PRICE ANOMALY" in m for m in caplog.messages)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_production_cost.py -v`
Expected: FAIL — `_update_output_cost_and_price` hozir `(db, out_wh_id, recipe, output_units, cost_per_unit)` signaturasi bilan; yangi `(db, out_wh_id, recipe, cost_per_unit, production)` chaqiruvi `production` ni `cost_per_unit` deb oladi, weighted-avg eski pp bilan aralashtiradi, history yo'q → assertlar yiqiladi.

- [ ] **Step 3: Add `_log_price_history` helper**

`app/routes/production.py` — `_update_output_cost_and_price` dan oldin qo'shing:

```python
def _log_price_history(db: Session, product, old_pp: float, new_pp: float, doc_number: str) -> None:
    """Production-driven purchase_price o'zgarishini tarixga yozadi (sukutda emas)."""
    if abs((old_pp or 0) - (new_pp or 0)) < 1e-6:
        return
    from app.models.database import ProductPriceHistory
    db.add(ProductPriceHistory(
        doc_number=doc_number,
        product_id=product.id,
        price_type_id=None,
        old_purchase_price=float(old_pp or 0),
        new_purchase_price=float(new_pp or 0),
        old_sale_price=float(product.sale_price or 0),
        new_sale_price=float(product.sale_price or 0),
        changed_by_id=None,
    ))
```

- [ ] **Step 4: Rewrite `_update_output_cost_and_price`**

`app/routes/production.py` — hozirgi to'liq funksiya (249-270):

```python
def _update_output_cost_and_price(db: Session, out_wh_id: int, recipe, output_units: float, cost_per_unit: float) -> None:
    """Tayyor mahsulotning Stock.cost_price va Product.purchase_price ni weighted average bilan yangilaydi."""
    product_stock = db.query(Stock).filter(
        Stock.warehouse_id == out_wh_id,
        Stock.product_id == recipe.product_id,
    ).first()
    if product_stock and hasattr(Stock, "cost_price"):
        qty_old = (product_stock.quantity or 0) - output_units
        cost_old = getattr(product_stock, "cost_price", None) or 0
        if qty_old <= 0 or cost_old <= 0:
            product_stock.cost_price = cost_per_unit
        else:
            product_stock.cost_price = (qty_old * cost_old + output_units * cost_per_unit) / (product_stock.quantity or 1)
    output_product = db.query(Product).filter(Product.id == recipe.product_id).first()
    if not output_product:
        return
    old_price = output_product.purchase_price or 0
    old_qty = (product_stock.quantity - output_units) if product_stock else 0
    if old_qty > 0 and old_price > 0 and output_units > 0:
        output_product.purchase_price = (old_qty * old_price + output_units * cost_per_unit) / (old_qty + output_units)
    elif cost_per_unit > 0:
        output_product.purchase_price = cost_per_unit
```

butunlay shu bilan almashtiriladi:

```python
def _update_output_cost_and_price(db: Session, out_wh_id: int, recipe, cost_per_unit: float, production) -> None:
    """Tayyor mahsulot Product.purchase_price + Stock.cost_price ni production'ning
    dona-boshiga material narxiga (cost_per_unit) flat tayinlaydi. Weighted-avg/self-feedback YO'Q
    (eski cheksiz-surilish bug'i ildizi). Har o'zgarish product_price_history'ga yoziladi."""
    output_product = db.query(Product).filter(Product.id == recipe.product_id).first()
    if not output_product:
        return
    cost = cost_per_unit
    if not cost or cost <= 0:
        return  # retsept/narx vaqtincha yo'q — eski qiymat saqlanadi (nolga tushirilmaydi)
    product_stock = db.query(Stock).filter(
        Stock.warehouse_id == out_wh_id,
        Stock.product_id == recipe.product_id,
    ).first()
    old = output_product.purchase_price or 0
    output_product.purchase_price = cost
    if product_stock is not None and hasattr(Stock, "cost_price"):
        product_stock.cost_price = cost
    _log_price_history(db, output_product, old, cost, production.number)
    if output_product.sale_price and cost > output_product.sale_price:
        logger.warning(
            "PRICE ANOMALY %s: tannarx %.0f > sotuv %.0f (xom ashyo narxi tekshirilsin)",
            output_product.name, cost, output_product.sale_price,
        )
```

- [ ] **Step 5: Update the caller**

`app/routes/production.py` ~319 — hozirgi:

```python
    _update_output_cost_and_price(db, out_wh_id, recipe, output_units, cost_per_unit)
```

bilan almashtiring:

```python
    _update_output_cost_and_price(db, out_wh_id, recipe, cost_per_unit, production)
```

(`cost_per_unit` va `production` ikkalasi ham shu scope'da mavjud — 300 va funksiya argumenti.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_production_cost.py -v`
Expected: PASS — 6 passed.

Regress: `python -m pytest tests/test_endpoints_smoke.py -q` → PASS.

- [ ] **Step 7: Commit**

```
git add app/routes/production.py tests/test_production_cost.py
git -c commit.gpgsign=false commit -m "fix(production): purchase_price feedback-rekursiya o'ldirildi (flat cost_per_unit + tarix + sanity-log)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Backfill skript `scripts/backfill_produced_purchase_price.py`

**Files:**
- Create: `scripts/backfill_produced_purchase_price.py`
- Test: `tests/test_production_cost.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_production_cost.py`)**

```python
def test_backfill_recomputes_per_unit_apply(db, tmp_path):
    """Backfill: 400gr SKU retsept dona-narxiga keladi (kg-narx EMAS), idempotent."""
    from app.models.database import Product, Recipe, RecipeItem, Stock
    import importlib.util, sys
    # Xom ashyo: 1 kg = 10000
    raw = Product(name="UN", code="UN", type="xom", is_active=True, purchase_price=10000, sale_price=0)
    db.add(raw); db.flush()
    out = Product(name="NON 400gr", code="NON400", type="tayyor", is_active=True,
                  purchase_price=999999, sale_price=20000)
    db.add(out); db.flush()
    r = Recipe(product_id=out.id, name="NON 400gr", output_quantity=1.0, is_active=True)
    db.add(r); db.flush()
    db.add(RecipeItem(recipe_id=r.id, product_id=raw.id, quantity=1.0))  # 1 kg un / partiya
    db.add(Stock(warehouse_id=1, product_id=out.id, quantity=5.0, cost_price=999999))
    db.commit()

    from app.routes.production import _calculate_recipe_cost_per_kg
    from app.utils.production_order import recipe_kg_per_unit
    expected = _calculate_recipe_cost_per_kg(db, r.id) * recipe_kg_per_unit(r)  # dona-narx

    spec = importlib.util.spec_from_file_location(
        "bf", "scripts/backfill_produced_purchase_price.py")
    bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)

    # DRY-RUN: yozmaydi
    bf.run(db, apply=False)
    db.refresh(out)
    assert out.purchase_price == 999999

    # APPLY: dona-narxga keladi
    bf.run(db, apply=True)
    db.refresh(out)
    assert abs(out.purchase_price - expected) < 1e-6
    assert expected < 999999            # 400gr per-unit kg-narxdan past, buzuq qiymat tuzaldi

    # Idempotent: 2-marta = bir xil
    bf.run(db, apply=True)
    db.refresh(out)
    assert abs(out.purchase_price - expected) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_production_cost.py::test_backfill_recomputes_per_unit_apply -v`
Expected: FAIL — `scripts/backfill_produced_purchase_price.py` mavjud emas.

- [ ] **Step 3: Create the script**

`scripts/backfill_produced_purchase_price.py`:

```python
"""Buzilgan ishlab chiqariladigan mahsulot purchase_price'ini retseptdan bir martalik backfill.

Jonli batch yo'q -> statik dona-narx: _calculate_recipe_cost_per_kg × recipe_kg_per_unit.
Default DRY-RUN (yozmaydi). --apply yozadi. Idempotent (deterministik).

Ishlatish:
    python scripts/backfill_produced_purchase_price.py [db_path] [--apply]
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import Product, Recipe, Stock, ProductPriceHistory
from app.routes.production import _calculate_recipe_cost_per_kg
from app.utils.production_order import recipe_kg_per_unit

DOC = "BACKFILL-" + datetime.now().strftime("%Y%m%d")


def run(db, *, apply: bool) -> list:
    """Har aktiv retseptli mahsulot uchun (old, new, flag). apply=True -> yozadi."""
    recipes = (
        db.query(Recipe)
        .filter(Recipe.is_active == True)  # noqa: E712
        .order_by(Recipe.id)
        .all()
    )
    seen: set = {}
    report = []
    for r in recipes:
        if r.product_id in seen:
            continue  # mahsulotda bir nechta retsept -> birinchisi (id bo'yicha)
        seen[r.product_id] = True
        p = db.query(Product).filter(Product.id == r.product_id).first()
        if not p:
            continue
        old = float(p.purchase_price or 0)
        new = _calculate_recipe_cost_per_kg(db, r.id) * recipe_kg_per_unit(r)
        flag = ""
        if new <= 0:
            flag = "SKIP(retsept bo'sh)"
        elif p.sale_price and new > p.sale_price:
            flag = "ANOMALY(new>sale)"
        report.append((p.id, p.name, old, new, flag))
        if apply and new > 0 and abs(old - new) >= 1e-6:
            p.purchase_price = new
            for s in db.query(Stock).filter(Stock.product_id == p.id).all():
                s.cost_price = new
            db.add(ProductPriceHistory(
                doc_number=DOC, product_id=p.id, price_type_id=None,
                old_purchase_price=old, new_purchase_price=float(new),
                old_sale_price=float(p.sale_price or 0),
                new_sale_price=float(p.sale_price or 0),
                changed_by_id=None,
            ))
    if apply:
        db.commit()
    return report


def main():
    args = [a for a in sys.argv[1:]]
    apply = "--apply" in args
    pos = [a for a in args if a != "--apply"]
    db_path = pos[0] if pos else "totli_holva.db"
    if not Path(db_path).exists():
        print(f"XATO: DB topilmadi: {db_path}")
        sys.exit(1)
    engine = create_engine(f"sqlite:///{db_path}")
    db = sessionmaker(bind=engine)()
    try:
        rep = run(db, apply=apply)
        mode = "APPLY" if apply else "DRY-RUN"
        print(f"[{mode}] {db_path} — {len(rep)} mahsulot")
        changed = anom = 0
        for pid, name, old, new, flag in sorted(rep, key=lambda x: -(x[3] or 0)):
            if flag or abs(old - new) >= 1e-6:
                pct = ((new - old) / old * 100) if old else 0
                star = " *" if "ANOMALY" in flag else ""
                print(f"  {pid:5} {name[:30]:30} {old:>12,.0f} -> {new:>12,.0f} "
                      f"({pct:+.0f}%) {flag}{star}")
                if abs(old - new) >= 1e-6 and new > 0:
                    changed += 1
                if "ANOMALY" in flag:
                    anom += 1
        print(f"O'zgaradi: {changed} | Anomaliya(new>sale): {anom}")
        if not apply:
            print("DRY-RUN — hech narsa yozilmadi. --apply bilan qo'llang.")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_production_cost.py -v`
Expected: PASS — 7 passed (Task 1 ning 6 tasi + backfill 1 ta).

- [ ] **Step 5: Commit**

```
git add scripts/backfill_produced_purchase_price.py tests/test_production_cost.py
git -c commit.gpgsign=false commit -m "feat(scripts): produced purchase_price backfill (retseptdan dona-narx, dry-run/apply, idempotent)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Deploy (birlashgan, tungi oyna — spec §6)

1. Branch `safe-fix-purchase-price` ← `feat-bulk-dispatch`. `git tag pre-purchase-price-YYYYMMDD` + DB dump.
2. **server2220'da** (ELYOR'dan emas) DRY-RUN: `python scripts\backfill_produced_purchase_price.py D:\TOTLI BI\totli_holva.db` — `old→new` + ANOMALY ro'yxati ko'rib chiqiladi. Anomaliya ko'p (ko'p mahsulotda new>sale) → TO'XTA, avval xom ashyo narxi tuzatiladi.
3. `python -m pytest tests/test_production_cost.py tests/test_endpoints_smoke.py -q` → PASS.
4. merge → **server2220 konsolida** `cd /d D:\TOTLI BI && taskkill /IM python.exe /F && start.bat`.
5. Backfill APPLY: `python scripts\backfill_produced_purchase_price.py D:\TOTLI BI\totli_holva.db --apply`.
6. Post-smoke: `10.243.165.156:8080` (127.0.0.1 EMAS) sold-products — MAYDA PISTA 1kg/KITOB 1 musbat marja; server.log XATO yo'q; 3-4 spot-check.
7. Rollback: kod `git revert`; ma'lumot — `BACKFILL-` tarix qatorlaridan `old_purchase_price` tiklash yoki DB dump restore (idempotent → qayta yuritish ham xavfsiz).

---

## Self-Review

**Spec coverage:** §2 forward arxitektura → Task 1 (cost_per_unit flat); §2 backfill recipe×kg/unit → Task 2; §3 helper+rewrite+signatura+caller → Task 1 Step 3-5; §3 `cost<=0` saqlanadi → test `..._zero_cost_keeps_old`; §3 anomaliya bloklamaydi → test `..._anomaly_warns_but_completes`; §3 changed_by_id=None → `_log_price_history`; §4 dry-run/apply/idempotent/only-if-changed/skip new<=0/anomaly/single-txn → Task 2 script + test; §5 testlar 1-7 → Task 1/2 testlari (recipe×kg/unit per-unit pin, idempotent, history, anomaly); §6 deploy → Deploy bo'limi. Gap yo'q.

**Placeholder scan:** TBD/TODO yo'q; har step to'liq kod/komanda. `YYYYMMDD` — deploy vaqtida hal bo'ladigan sana shablon (skript ichida `datetime.now()` avtomatik).

**Type consistency:** `_update_output_cost_and_price(db, out_wh_id, recipe, cost_per_unit, production)` — Task 1 Step 4 ta'rifi, Step 5 chaqiruvi, testlar bir xil 5-argument tartibi. `_log_price_history(db, product, old_pp, new_pp, doc_number)` — Task 1 Step 3 ta'rifi, Step 4 chaqiruvi mos. Backfill `run(db, *, apply)` — Task 2 script + test bir xil.
