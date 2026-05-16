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
from app.utils.production_order import recipe_kg_per_unit


def _own_cost_per_kg(db, recipe, recipes_by_pid: dict, memo: dict, stack: set) -> float:
    """Backfill uchun TO'G'RI fixed-point retsept tannarxi (kg boshiga).
    _calculate_recipe_cost_per_kg nusxasi, BITTA farq: aktiv retsepti BOR har qanday
    input (tur muhim emas) rekursiya qilinadi (saqlangan buzuq pp emas).
    Faqat aktiv retseptsiz input (haqiqiy xom ashyo / retseptsiz semi) saqlangan
    purchase_price/Stock.cost_price ga tushadi. Memoizatsiya + cycle-guard."""
    rid = recipe.id
    if rid in memo:
        return memo[rid]
    if rid in stack:
        return 0.0  # cycle guard
    if not recipe.items:
        memo[rid] = 0.0
        return 0.0
    stack.add(rid)
    pids = [it.product_id for it in recipe.items]
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}
    stocks: dict = {}
    for s in db.query(Stock).filter(Stock.product_id.in_(pids)).all():
        stocks.setdefault(s.product_id, s)
    total = 0.0
    for it in recipe.items:
        p = products.get(it.product_id)
        if not p:
            continue
        sub = recipes_by_pid.get(p.id)  # ANY active recipe for this input?
        if sub is not None:
            unit = _own_cost_per_kg(db, sub, recipes_by_pid, memo, stack)
            total += (it.quantity or 0) * unit
        else:
            cost = p.purchase_price or 0
            st = stocks.get(p.id)
            if st is not None and getattr(st, "cost_price", None) and st.cost_price > 0:
                cost = st.cost_price
            total += (it.quantity or 0) * cost
    stack.discard(rid)
    okg = recipe_kg_per_unit(recipe)
    res = (total / okg) if okg and okg > 0 else 0.0
    memo[rid] = res
    return res


def _next_doc(db, prefix: str) -> str:
    last = (
        db.query(ProductPriceHistory)
        .filter(ProductPriceHistory.doc_number.like(f"{prefix}%"))
        .order_by(ProductPriceHistory.id.desc())
        .first()
    )
    try:
        num = (int(last.doc_number.rsplit("-", 1)[-1]) + 1) if last and last.doc_number else 1
    except (ValueError, IndexError):
        num = 1
    return f"{prefix}{num:03d}"


def run(db, *, apply: bool) -> list:
    """Phase 1: own fixed-point cost bilan barcha new'ni YOZMASDAN hisobla.
    Phase 2: apply bo'lsa Phase 1 natijalaridan yoz. Idempotent fixed-point."""
    prefix = f"BACKFILL-{datetime.now().strftime('%Y%m%d')}-"
    active = (
        db.query(Recipe)
        .filter(Recipe.is_active == True)  # noqa: E712
        .order_by(Recipe.id)
        .all()
    )
    recipes_by_pid: dict = {}
    for r in active:
        recipes_by_pid.setdefault(r.product_id, r)
    memo: dict = {}
    stack: set = set()
    plan = []
    report = []
    for pid, r in recipes_by_pid.items():
        p = db.query(Product).filter(Product.id == pid).first()
        if not p:
            continue
        old = float(p.purchase_price or 0)
        new = _own_cost_per_kg(db, r, recipes_by_pid, memo, stack) * recipe_kg_per_unit(r)
        flag = ""
        if new <= 0:
            flag = "SKIP(retsept bo'sh)"
        elif p.sale_price and new > p.sale_price:
            flag = "ANOMALY(new>sale)"
        elif old > 0 and abs(new - old) / old > 0.70:
            flag = "SUSPECT(>70%)"
        plan.append((p, old, new, flag))
        report.append((p.id, p.name, old, new, flag))
    if apply:
        for p, old, new, flag in plan:
            if new > 0 and abs(old - new) >= 1e-6:
                p.purchase_price = new
                for s in db.query(Stock).filter(Stock.product_id == p.id).all():
                    s.cost_price = new
                db.add(ProductPriceHistory(
                    doc_number=_next_doc(db, prefix),
                    product_id=p.id,
                    price_type_id=None,
                    old_purchase_price=old,
                    new_purchase_price=float(new),
                    old_sale_price=float(p.sale_price or 0),
                    new_sale_price=float(p.sale_price or 0),
                    changed_by_id=None,
                ))
                db.flush()
        db.commit()
    return report


def main():
    args = sys.argv[1:]
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
        changed = anom = suspect = 0
        for pid, name, old, new, flag in sorted(rep, key=lambda x: -(x[3] or 0)):
            if flag or abs(old - new) >= 1e-6:
                pct = ((new - old) / old * 100) if old else 0
                if "ANOMALY" in flag:
                    star = " *"
                elif flag.startswith("SUSPECT"):
                    star = " ~"
                else:
                    star = ""
                print(f"  {pid:5} {name[:30]:30} {old:>12,.0f} -> {new:>12,.0f} "
                      f"({pct:+.0f}%) {flag}{star}")
                if abs(old - new) >= 1e-6 and new > 0:
                    changed += 1
                if "ANOMALY" in flag:
                    anom += 1
                if flag.startswith("SUSPECT"):
                    suspect += 1
        print(f"O'zgaradi: {changed} | Anomaliya: {anom} | Suspect(>70%): {suspect}")
        if not apply:
            print("DRY-RUN — hech narsa yozilmadi. --apply bilan qo'llang.")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
