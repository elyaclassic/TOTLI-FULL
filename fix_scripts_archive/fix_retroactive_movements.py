"""
Retroaktiv stock_movement yaratish — 403 ta completed production uchun.
Bug: a8404fb (Mar 12) -> 55a23ec (Mar 25) orasida stock_movements yozilmagan.
Stocklar TO'G'RI — faqat tarix (audit trail) yozamiz.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)


def get_warehouse_id_for_ingredient(db, product_id, production_warehouse_id):
    """Yarim tayyor -> 'yarim' nomli ombor, boshqa -> production.warehouse_id"""
    row = db.execute(
        text("SELECT type FROM products WHERE id=:pid"), {"pid": product_id}
    ).fetchone()
    if not row or row[0] != "yarim_tayyor":
        return production_warehouse_id

    # Yarim tayyor: nomida 'yarim' bor ombordan qidirish
    stocks = db.execute(
        text("""
            SELECT s.warehouse_id, w.name, w.code
            FROM stocks s JOIN warehouses w ON w.id=s.warehouse_id
            WHERE s.product_id=:pid AND s.quantity > 0
        """), {"pid": product_id}
    ).fetchall()
    for st in stocks:
        name = (st[1] or "").lower()
        code = (st[2] or "").lower()
        if "yarim" in name or "semi" in name or "yarim" in code or "semi" in code:
            return st[0]
    if stocks:
        return stocks[0][0]
    return production_warehouse_id


def fix():
    db = Session()
    try:
        # 1. Broken productionlarni topish
        broken = db.execute(text("""
            SELECT p.id, p.number, p.date, p.warehouse_id, p.output_warehouse_id,
                   p.recipe_id, p.quantity, p.created_at
            FROM productions p
            WHERE p.status='completed'
            AND (SELECT COUNT(*) FROM stock_movements sm WHERE sm.document_number=p.number) = 0
            ORDER BY p.date
        """)).fetchall()

        print(f"Topildi: {len(broken)} ta broken production")
        if not broken:
            print("Hech narsa tuzatish kerak emas.")
            return

        total_consumption = 0
        total_output = 0
        errors = []

        for prod in broken:
            prod_id, prod_number, prod_date, wh_id, out_wh_id, recipe_id, prod_qty, created_at = prod
            if not out_wh_id:
                out_wh_id = wh_id

            # Production items (agar bo'lsa)
            items = db.execute(text("""
                SELECT pi.product_id, pi.quantity
                FROM production_items pi
                WHERE pi.production_id=:pid AND pi.quantity > 0
            """), {"pid": prod_id}).fetchall()

            # Agar production_items bo'lmasa, recipe_items dan olish
            if not items:
                items = db.execute(text("""
                    SELECT ri.product_id, ri.quantity * :qty as quantity
                    FROM recipe_items ri
                    WHERE ri.recipe_id=:rid AND ri.quantity > 0
                """), {"rid": recipe_id, "qty": prod_qty}).fetchall()

            # Har bir ingredient uchun consumption movement
            for item in items:
                product_id, qty = item
                if qty is None or qty <= 0:
                    continue

                ingredient_wh_id = get_warehouse_id_for_ingredient(db, product_id, wh_id)

                # Stock topish
                stock_row = db.execute(text("""
                    SELECT id, quantity FROM stocks
                    WHERE warehouse_id=:wid AND product_id=:pid
                """), {"wid": ingredient_wh_id, "pid": product_id}).fetchone()

                stock_id = stock_row[0] if stock_row else None
                current_qty = stock_row[1] if stock_row else 0

                if stock_id is None:
                    # Stock yo'q — skip (bu aslida bo'lmasligi kerak)
                    continue

                db.execute(text("""
                    INSERT INTO stock_movements
                    (stock_id, warehouse_id, product_id, operation_type, document_type,
                     document_id, document_number, quantity_change, quantity_after, note, created_at)
                    VALUES (:stock_id, :wh_id, :product_id, 'production_consumption', 'Production',
                            :doc_id, :doc_number, :qty_change, :qty_after,
                            :note, :created_at)
                """), {
                    "stock_id": stock_id,
                    "wh_id": ingredient_wh_id,
                    "product_id": product_id,
                    "doc_id": prod_id,
                    "doc_number": prod_number,
                    "qty_change": -qty,
                    "qty_after": current_qty,  # hozirgi qoldiq (tarixiy emas)
                    "note": f"[RETROAKTIV] Ishlab chiqarish (xom ashyo): {prod_number}",
                    "created_at": created_at or prod_date,
                })
                total_consumption += 1

            # Tayyor mahsulot output movement
            recipe_row = db.execute(text("""
                SELECT product_id FROM recipes WHERE id=:rid
            """), {"rid": recipe_id}).fetchone()

            if recipe_row:
                output_product_id = recipe_row[0]

                # Output miqdorni aniqlash
                # product type va unit tekshirish
                product_row = db.execute(text("""
                    SELECT p.type, u.name FROM products p
                    LEFT JOIN units u ON u.id=p.unit_id
                    WHERE p.id=:pid
                """), {"pid": output_product_id}).fetchone()

                unit_name = (product_row[1] or "").lower() if product_row else ""
                if "dona" in unit_name or "ta" in unit_name:
                    output_units = prod_qty
                else:
                    # kg hisoblash — recipe_kg_per_unit logic
                    recipe_items_sum = db.execute(text("""
                        SELECT COALESCE(SUM(ri.quantity), 0) FROM recipe_items ri WHERE ri.recipe_id=:rid
                    """), {"rid": recipe_id}).fetchone()[0]
                    output_units = prod_qty * recipe_items_sum if recipe_items_sum > 0 else prod_qty

                out_stock = db.execute(text("""
                    SELECT id, quantity FROM stocks
                    WHERE warehouse_id=:wid AND product_id=:pid
                """), {"wid": out_wh_id, "pid": output_product_id}).fetchone()

                if out_stock:
                    db.execute(text("""
                        INSERT INTO stock_movements
                        (stock_id, warehouse_id, product_id, operation_type, document_type,
                         document_id, document_number, quantity_change, quantity_after, note, created_at)
                        VALUES (:stock_id, :wh_id, :product_id, 'production_output', 'Production',
                                :doc_id, :doc_number, :qty_change, :qty_after,
                                :note, :created_at)
                    """), {
                        "stock_id": out_stock[0],
                        "wh_id": out_wh_id,
                        "product_id": output_product_id,
                        "doc_id": prod_id,
                        "doc_number": prod_number,
                        "qty_change": output_units,
                        "qty_after": out_stock[1],
                        "note": f"[RETROAKTIV] Ishlab chiqarish (tayyor mahsulot): {prod_number}",
                        "created_at": created_at or prod_date,
                    })
                    total_output += 1

        db.commit()
        print(f"\nYakunlandi:")
        print(f"  Consumption movements: {total_consumption}")
        print(f"  Output movements: {total_output}")
        print(f"  Jami: {total_consumption + total_output}")

        # Tekshirish
        new_count = db.execute(text("SELECT COUNT(*) FROM stock_movements")).fetchone()[0]
        print(f"\n  Oldingi movement soni: 6135")
        print(f"  Yangi movement soni: {new_count}")
        print(f"  Qo'shildi: {new_count - 6135}")

    except Exception as e:
        db.rollback()
        print(f"XATO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    fix()
