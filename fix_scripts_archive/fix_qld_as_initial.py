"""
WH1: QLD-20260216-0001 ni boshlang'ich qoldiq sifatida to'g'rilash.

1. QLD movement: quantity_change = +QLD_target (bu boshlang'ich qoldiq)
2. initial_balance: o'chirish (QLD o'rnini bosadi)
3. stocks.quantity = sum(all movements) yoki 0 (agar manfiy)
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///D:/TOTLI BI/totli_holva.db", echo=False)
Session = sessionmaker(bind=engine)


def fix():
    db = Session()
    try:
        # QLD-20260216-0001 mahsulotlari (WH1)
        qld_items = db.execute(text("""
            SELECT sadi.product_id, sadi.quantity as target, p.code
            FROM stock_adjustment_doc_items sadi
            JOIN stock_adjustment_docs sad ON sad.id=sadi.doc_id
            JOIN products p ON p.id=sadi.product_id
            WHERE sad.number='QLD-20260216-0001'
        """)).fetchall()

        print(f"QLD-20260216-0001: {len(qld_items)} ta mahsulot")

        for item in qld_items:
            pid, target, code = item

            # 1. initial_balance ni o'chirish (QLD o'rnini bosadi)
            db.execute(text("""
                DELETE FROM stock_movements
                WHERE warehouse_id=1 AND product_id=:pid AND operation_type='initial_balance'
            """), {"pid": pid})

            # 2. QLD movement ni to'g'rilash: quantity_change = +target
            db.execute(text("""
                UPDATE stock_movements
                SET quantity_change = :target, quantity_after = :target
                WHERE warehouse_id=1 AND product_id=:pid
                AND document_number='QLD-20260216-0001'
                AND operation_type='adjustment'
            """), {"pid": pid, "target": target})

            # 3. Barcha movementlar yig'indisini hisoblash
            total = db.execute(text("""
                SELECT COALESCE(SUM(quantity_change), 0) FROM stock_movements
                WHERE warehouse_id=1 AND product_id=:pid
            """), {"pid": pid}).fetchone()[0]

            # 4. Manfiy bo'lsa 0, aks holda yig'indi
            new_qty = max(round(total, 4), 0)

            # 5. stocks.quantity yangilash
            db.execute(text("""
                UPDATE stocks SET quantity = :qty WHERE warehouse_id=1 AND product_id=:pid
            """), {"qty": new_qty, "pid": pid})

            # 6. Agar manfiy edi — balance_correction qo'shish
            if total < -0.01:
                # Manfiy farqni tuzatish
                db.execute(text("""
                    INSERT INTO stock_movements
                    (stock_id, warehouse_id, product_id, operation_type, document_type,
                     document_id, document_number, quantity_change, quantity_after, note, created_at)
                    VALUES (
                        (SELECT id FROM stocks WHERE warehouse_id=1 AND product_id=:pid),
                        1, :pid, 'balance_correction', 'BalanceCorrection', 0, 'CORR-BALANCE',
                        :corr, 0, '[QOLDIQ TUZATISH] Ortiqcha chiqim (inflated stock)',
                        '2026-03-27 21:00:00')
                """), {"pid": pid, "corr": -total})

            old_qty_row = db.execute(text("""
                SELECT quantity FROM stocks WHERE warehouse_id=1 AND product_id=:pid
            """), {"pid": pid}).fetchone()

            print(f"  {code}: QLD={target}, movements_sum={round(total,2)}, stock={new_qty}")

        db.commit()

        # Yakuniy tekshirish
        diff_count = db.execute(text("""
            SELECT COUNT(*) FROM stocks s
            WHERE s.warehouse_id=1
            AND ABS(ROUND(s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm
                WHERE sm.warehouse_id=s.warehouse_id AND sm.product_id=s.product_id), 0), 2)) > 0.01
        """)).fetchone()[0]
        print(f"\nWH1 qolgan diff: {diff_count}")

        neg = db.execute(text("""
            SELECT COUNT(*) FROM stocks WHERE warehouse_id=1 AND quantity < -0.01
        """)).fetchone()[0]
        print(f"WH1 manfiy stock: {neg}")

    except Exception as e:
        db.rollback()
        print(f"XATO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    fix()
