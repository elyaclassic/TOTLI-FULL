"""Bugun mavjud AGT-018 (waiting_production) uchun retroaktiv Production yaratish.

Mening yangi auto_create_productions_for_order qo'shilganidan oldin
yaratilgan order uchun bir martalik fix.
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "totli_holva.db"


def main():
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    # Bugungi waiting_production orderlar (production hujjat hali yo'q bo'lganlari)
    cur.execute("""
        SELECT o.id, o.number, o.note
        FROM orders o
        WHERE o.status='waiting_production' AND o.created_at >= '2026-05-06'
          AND NOT EXISTS (SELECT 1 FROM productions WHERE order_id=o.id)
        ORDER BY o.id
    """)
    orders = cur.fetchall()
    if not orders:
        print("Production talab qiladigan order yo'q (yoki hammasiga production yaratilgan)")
        return 0

    today = datetime.now()
    prefix = f"PR-{today.strftime('%Y%m%d')}"
    cur.execute(
        "SELECT number FROM productions WHERE number LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}-%",),
    )
    last = cur.fetchone()
    try:
        seq = int(last[0].split("-")[-1]) + 1 if last else 1
    except (ValueError, IndexError):
        seq = 1

    for oid, onum, _ in orders:
        # Order itemlari va Stock holati
        cur.execute("""
            SELECT oi.product_id, p.name, oi.quantity,
                   COALESCE(s.quantity, 0) AS in_stock
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            LEFT JOIN stocks s ON s.product_id = oi.product_id AND s.warehouse_id = 3
            WHERE oi.order_id = ?
        """, (oid,))
        items = cur.fetchall()
        shortage = [
            (pid, name, qty)
            for pid, name, qty, have in items
            if (have or 0) + 1e-6 < (qty or 0)
        ]
        if not shortage:
            print(f"{onum}: Stock yetarli, production kerak emas")
            continue

        print(f"\n→ {onum} (id={oid}) — {len(shortage)} ta mahsulot kerak:")
        for pid, name, qty in shortage:
            # Recipe topish
            cur.execute("""
                SELECT id, default_warehouse_id, default_output_warehouse_id
                FROM recipes WHERE product_id=? AND is_active=1
                ORDER BY id DESC LIMIT 1
            """, (pid,))
            recipe = cur.fetchone()
            if not recipe:
                print(f"  ⚠ {name}: recipe topilmadi (manual production kerak)")
                continue
            r_id, def_wh, def_out_wh = recipe
            number = f"{prefix}-{seq:03d}"
            cur.execute("""
                INSERT INTO productions
                    (number, date, recipe_id, warehouse_id, output_warehouse_id,
                     quantity, status, note, order_id, current_stage, max_stage, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, 0, 0, ?)
            """, (
                number, today, r_id, def_wh, def_out_wh,
                qty, f"Auto: {onum} (Stock=0). Operator yakunlasin.", oid, today,
            ))
            print(f"  ✓ {number}: {name} × {qty}")
            seq += 1

    conn.commit()
    conn.close()
    print("\n✅ Tayyor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
