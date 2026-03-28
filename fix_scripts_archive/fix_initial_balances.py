"""
Qadam 2: Boshlang'ich qoldiqlar uchun 'initial_balance' movement yaratish.
Faqat positive diff (actual > movements_sum) uchun.
Sana: har bir mahsulotning birinchi movementidan 1 soniya oldin, yoki 2026-02-16 00:00:00.
Stocks jadvaliga TEGMAYMIZ — faqat movement (tarix) yozamiz.
"""
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)

SYSTEM_START = "2026-02-16 00:00:00"


def fix():
    db = Session()
    try:
        # Barcha positive diff larni topish
        rows = db.execute(text("""
            SELECT s.id as stock_id, s.warehouse_id, s.product_id,
              s.quantity as actual,
              COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0) as movements_sum
            FROM stocks s
            WHERE s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0) > 0.01
        """)).fetchall()

        print(f"Topildi: {len(rows)} ta mahsulot boshlang'ich qoldiq kerak")
        count = 0

        for row in rows:
            stock_id, wh_id, product_id, actual, movements_sum = row
            diff = round(actual - movements_sum, 4)

            # Bu mahsulotning birinchi movement sanasini topish
            first_movement = db.execute(text("""
                SELECT MIN(created_at) FROM stock_movements
                WHERE warehouse_id=:wid AND product_id=:pid
            """), {"wid": wh_id, "pid": product_id}).fetchone()[0]

            if first_movement:
                # Birinchi movementdan 1 soniya oldin
                dt = datetime.fromisoformat(first_movement) - timedelta(seconds=1)
                created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_at = SYSTEM_START

            db.execute(text("""
                INSERT INTO stock_movements
                (stock_id, warehouse_id, product_id, operation_type, document_type,
                 document_id, document_number, quantity_change, quantity_after, note, created_at)
                VALUES (:stock_id, :wh_id, :product_id, 'initial_balance', 'InitialBalance',
                        0, 'INIT-BALANCE', :qty_change, :qty_change,
                        :note, :created_at)
            """), {
                "stock_id": stock_id,
                "wh_id": wh_id,
                "product_id": product_id,
                "qty_change": diff,
                "note": f"[BOSHLANG'ICH QOLDIQ] Tizim ishga tushganidagi qoldiq",
                "created_at": created_at,
            })
            count += 1

        db.commit()
        print(f"Yaratildi: {count} ta initial_balance movement")

        # Tekshirish: endi nechta positive diff qoldi?
        remaining = db.execute(text("""
            SELECT COUNT(*) FROM stocks s
            WHERE s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0) > 0.01
        """)).fetchone()[0]
        print(f"Qolgan positive diff: {remaining}")

    except Exception as e:
        db.rollback()
        print(f"XATO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    fix()
