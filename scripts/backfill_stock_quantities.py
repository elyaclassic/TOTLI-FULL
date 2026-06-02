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

from app.models.database import SessionLocal, Stock, Warehouse, Product, StockMovement
from app.services.stock_service import compute_stock_quantity, reconcile_stock

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    try:
        wh = {w.id: w.name for w in db.query(Warehouse).all()}
        pn = {p.id: p.name for p in db.query(Product).all()}
        changes = []
        for s in db.query(Stock).all():
            mc = db.query(StockMovement).filter(
                StockMovement.warehouse_id == s.warehouse_id,
                StockMovement.product_id == s.product_id).count()
            if mc == 0:
                continue
            stored = float(s.quantity or 0)
            computed = compute_stock_quantity(db, s.warehouse_id, s.product_id)
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
