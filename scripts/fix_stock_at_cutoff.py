"""
08.04.2026 23:59:59 holatiga stock tuzatish utility.

Foydalanish:
    python scripts/fix_stock_at_cutoff.py <warehouse_id> <code> <target_qty>
    masalan: python scripts/fix_stock_at_cutoff.py 2 P226 4.07
"""
import sys
from datetime import datetime
from app.models.database import SessionLocal, Product, Stock, StockMovement


def fix_stock(wid: int, code: str, target: float):
    db = SessionLocal()
    p = db.query(Product).filter(Product.code == code).first()
    if not p:
        print(f"❌ Product topilmadi: {code}")
        db.close()
        return

    stock = db.query(Stock).filter(Stock.warehouse_id == wid, Stock.product_id == p.id).first()
    if not stock:
        stock = Stock(warehouse_id=wid, product_id=p.id, quantity=0)
        db.add(stock)
        db.flush()

    cutoff = datetime(2026, 4, 8, 23, 59, 59)

    # Eski CORR ni olib tashlash
    old_corr = db.query(StockMovement).filter(
        StockMovement.warehouse_id == wid, StockMovement.product_id == p.id,
        StockMovement.document_type == "ManualCorrection",
        StockMovement.document_number == "CORR-20260408",
    ).all()
    old_delta = sum(float(m.quantity_change or 0) for m in old_corr)
    for m in old_corr:
        db.delete(m)
    db.flush()

    restored = float(stock.quantity) - old_delta
    after = db.query(StockMovement).filter(
        StockMovement.warehouse_id == wid, StockMovement.product_id == p.id,
        StockMovement.created_at > cutoff,
    ).all()
    after_change = sum(float(m.quantity_change or 0) for m in after)
    calc_cutoff = restored - after_change

    new_current = round(target + after_change, 3)
    if new_current < 0:
        new_current = 0
    delta = round(new_current - restored, 3)

    if abs(delta) > 0.001:
        db.add(StockMovement(
            stock_id=stock.id, warehouse_id=wid, product_id=p.id,
            operation_type="manual_correction", document_type="ManualCorrection",
            document_id=0, document_number="CORR-20260408",
            quantity_change=delta, quantity_after=new_current,
            note=f"Qo'lda tuzatish: 08.04.2026 oxiri qoldig'i {target}",
            created_at=cutoff,
        ))
    stock.quantity = new_current
    db.commit()
    print(f"✓ {p.name} ({p.code}): 08.04 oxiri {calc_cutoff:.3f} → {target} | hozirgi: {new_current}")
    db.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Foydalanish: python scripts/fix_stock_at_cutoff.py <warehouse_id> <code> <target_qty>")
        sys.exit(1)
    fix_stock(int(sys.argv[1]), sys.argv[2], float(sys.argv[3]))
