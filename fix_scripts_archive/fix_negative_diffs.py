"""
Qadam 5: Negative diff lar uchun balance_correction movement yaratish.
Bu mahsulotlarda actual < movements_sum — ya'ni chiqim bo'lgan lekin movement yozilmagan.
Stocks jadvaliga TEGMAYMIZ.
"""
import os
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)


def fix():
    db = Session()
    try:
        rows = db.execute(text("""
            SELECT s.id as stock_id, s.warehouse_id, s.product_id,
              ROUND(s.quantity, 4) as actual,
              ROUND(COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0), 4) as movements_sum
            FROM stocks s
            WHERE ROUND(s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0), 2) < -0.01
        """)).fetchall()

        print(f"Topildi: {len(rows)} ta negative diff")
        count = 0

        for row in rows:
            stock_id, wh_id, product_id, actual, movements_sum = row
            # diff = actual - movements_sum (manfiy bo'ladi)
            diff = round(actual - movements_sum, 4)

            # Oxirgi movement sanasini topish
            last_movement = db.execute(text("""
                SELECT MAX(created_at) FROM stock_movements
                WHERE warehouse_id=:wid AND product_id=:pid
            """), {"wid": wh_id, "pid": product_id}).fetchone()[0]

            # Ombor va mahsulot nomini olish (log uchun)
            info = db.execute(text("""
                SELECT w.name, p.code, p.name
                FROM warehouses w, products p
                WHERE w.id=:wid AND p.id=:pid
            """), {"wid": wh_id, "pid": product_id}).fetchone()
            wh_name, p_code, p_name = info

            created_at = last_movement or "2026-03-27 00:00:00"

            db.execute(text("""
                INSERT INTO stock_movements
                (stock_id, warehouse_id, product_id, operation_type, document_type,
                 document_id, document_number, quantity_change, quantity_after, note, created_at)
                VALUES (:stock_id, :wh_id, :product_id, 'balance_correction', 'BalanceCorrection',
                        0, 'CORR-BALANCE', :qty_change, :actual,
                        :note, :created_at)
            """), {
                "stock_id": stock_id,
                "wh_id": wh_id,
                "product_id": product_id,
                "qty_change": diff,  # manfiy qiymat
                "actual": actual,
                "note": f"[QOLDIQ TUZATISH] Yozilmagan chiqimlar tuzatmasi ({wh_name})",
                "created_at": created_at,
            })
            print(f"  {wh_name}: {p_code} {p_name} — diff={diff}")
            count += 1

        db.commit()
        print(f"\nYaratildi: {count} ta balance_correction movement")

        # Tekshirish
        remaining = db.execute(text("""
            SELECT COUNT(*) FROM stocks s
            WHERE ABS(ROUND(s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0), 2)) > 0.01
        """)).fetchone()[0]
        print(f"Qolgan diff (abs > 0.01): {remaining}")

    except Exception as e:
        db.rollback()
        print(f"XATO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    fix()
