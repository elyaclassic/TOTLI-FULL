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
    """Har aktiv retseptli mahsulot uchun (id, name, old, new, flag). apply -> yozadi."""
    prefix = f"BACKFILL-{datetime.now().strftime('%Y%m%d')}-"
    recipes = (
        db.query(Recipe)
        .filter(Recipe.is_active == True)  # noqa: E712
        .order_by(Recipe.id)
        .all()
    )
    seen: set = set()
    report = []
    for r in recipes:
        if r.product_id in seen:
            continue
        seen.add(r.product_id)
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
    if apply:
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
