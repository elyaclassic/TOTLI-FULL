"""
QLD DOUBLE BUG tuzatish.
Muammo: Adjustment hujjatlarda quantity_after = 2 * target_qty.
Sabab: create_stock_movement duplikat stock qatorlarini birlashtirganda stock.quantity
       allaqachon target_qty ga teng bo'lgan, keyin yana quantity_change qo'shilgan.

Fix:
1. Movement: quantity_change = 0 (qoldiq allaqachon to'g'ri edi), quantity_after = target_qty
2. Stocks: quantity -= target_qty (ortiqcha qo'shilgan miqdorni ayirish)
3. Initial_balance: ham tuzatish kerak (chunki u actual stockga asoslangan edi)
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)


def fix():
    db = Session()
    try:
        # DOUBLE BUG movementlarni topish
        bugs = db.execute(text("""
            SELECT sm.id as movement_id, sm.warehouse_id, sm.product_id,
              sadi.quantity as target_qty,
              sm.quantity_change, sm.quantity_after,
              sm.document_number
            FROM stock_movements sm
            JOIN stock_adjustment_doc_items sadi ON sadi.product_id=sm.product_id
            JOIN stock_adjustment_docs sad ON sad.id=sadi.doc_id AND sad.number=sm.document_number
            WHERE sm.operation_type='adjustment' AND sm.document_type='StockAdjustmentDoc'
            AND ABS(sm.quantity_after - 2*sadi.quantity) < 0.1
            AND sadi.quantity > 0
        """)).fetchall()

        print(f"Topildi: {len(bugs)} ta DOUBLE BUG movement")

        for bug in bugs:
            mv_id, wh_id, product_id, target_qty, mv_change, mv_after, doc_number = bug

            info = db.execute(text("""
                SELECT w.name, p.code FROM warehouses w, products p
                WHERE w.id=:wid AND p.id=:pid
            """), {"wid": wh_id, "pid": product_id}).fetchone()
            wh_name, p_code = info

            # 1. Movement tuzatish: quantity_change=0 bo'lishi kerak edi
            #    (qoldiq allaqachon target_qty edi, o'zgarish kerak emas edi)
            db.execute(text("""
                UPDATE stock_movements
                SET quantity_change = 0, quantity_after = :target,
                    note = note || ' [TUZATILDI: double bug fix]'
                WHERE id = :mid
            """), {"target": target_qty, "mid": mv_id})

            # 2. Stocks.quantity -= target_qty (ortiqcha qo'shilganini qaytarish)
            db.execute(text("""
                UPDATE stocks SET quantity = quantity - :excess
                WHERE warehouse_id = :wid AND product_id = :pid
            """), {"excess": target_qty, "wid": wh_id, "pid": product_id})

            # 3. Initial_balance tuzatish (u ham actual stockga asoslangan edi)
            db.execute(text("""
                UPDATE stock_movements
                SET quantity_change = quantity_change - :excess,
                    quantity_after = quantity_after - :excess
                WHERE warehouse_id = :wid AND product_id = :pid
                AND operation_type = 'initial_balance'
            """), {"excess": target_qty, "wid": wh_id, "pid": product_id})

            print(f"  {wh_name}: {p_code} — stock -{target_qty}")

        db.commit()
        print(f"\nTuzatildi: {len(bugs)} ta")

        # Tekshirish
        remaining = db.execute(text("""
            SELECT COUNT(*) FROM stocks s
            LEFT JOIN (SELECT warehouse_id, product_id, SUM(quantity_change) as total
                       FROM stock_movements GROUP BY warehouse_id, product_id) m
            ON m.warehouse_id=s.warehouse_id AND m.product_id=s.product_id
            WHERE ABS(ROUND(s.quantity - COALESCE(m.total, 0), 2)) > 0.01
            AND (s.quantity != 0 OR m.total IS NOT NULL)
        """)).fetchone()[0]
        print(f"Qolgan diff: {remaining}")

        # P106 tekshirish
        p106 = db.execute(text("""
            SELECT s.quantity FROM stocks s WHERE s.warehouse_id=1 AND s.product_id=60
        """)).fetchone()
        print(f"\nP106 Xom ashyo ombori: {p106[0]}")

        # Manfiy stock tekshirish
        negatives = db.execute(text("""
            SELECT w.name, p.code, s.quantity FROM stocks s
            JOIN warehouses w ON w.id=s.warehouse_id
            JOIN products p ON p.id=s.product_id
            WHERE s.quantity < -0.01
        """)).fetchall()
        if negatives:
            print(f"\nOGOHLANTIRISH - Manfiy qoldiqlar:")
            for n in negatives:
                print(f"  {n[0]}: {n[1]} = {n[2]}")
        else:
            print("Manfiy qoldiq: yo'q")

    except Exception as e:
        db.rollback()
        print(f"XATO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    fix()
