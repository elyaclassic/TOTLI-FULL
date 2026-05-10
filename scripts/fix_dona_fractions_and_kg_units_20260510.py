"""Donalik mahsulotda kasr + RULET kg unit tuzatish — 2026-05-10

2 turli muammo birga tuzatadi:

1. Donalik (unit.code='ta') stock'larda kasr — round() qilib audit movement bilan rasmiylashtirish
2. Sof kg mahsulotlar (RULET MALINA kg, RULET PISTALI kg, RULET KESHULI kg, BUTUN PISTA kg, Keshu 1 kg) ning unit_id ni dona dan kg ga ko'chirish

Audit: order_items=0 ekanligi tekshirilgan, demak xavf juda past.

Ishlatish:
    python scripts/fix_dona_fractions_and_kg_units_20260510.py        # --dry-run (default)
    python scripts/fix_dona_fractions_and_kg_units_20260510.py --apply
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


KG_PRODUCTS = [156, 157, 158, 230, 363, 369]


def main(argv):
    apply = "--apply" in argv
    dry = not apply

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print("=" * 70)
    print(f"FIX DONA FRACTIONS + KG UNITS — {'DRY-RUN' if dry else 'APPLY'}")
    print("=" * 70)

    cur.execute("SELECT id FROM units WHERE code='ta'")
    ta_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM units WHERE code='kg'")
    kg_id = cur.fetchone()[0]
    print(f"\nUnit IDs: ta={ta_id}, kg={kg_id}")

    # 1) Donalik kasrli stocklar
    cur.execute(f"""
        SELECT s.id, s.warehouse_id, s.product_id, p.name, s.quantity
        FROM stocks s
        JOIN products p ON p.id = s.product_id
        WHERE p.unit_id = {ta_id}
          AND ABS(s.quantity - ROUND(s.quantity)) > 0.001
          AND s.product_id NOT IN ({','.join(str(x) for x in KG_PRODUCTS)})
        ORDER BY s.id
    """)
    fractional_stocks = cur.fetchall()
    print(f"\n--- 1. Donalik kasrli stocklar ({len(fractional_stocks)} ta) ---")
    for sid, wid, pid, pname, qty in fractional_stocks:
        rounded = round(qty)
        diff = qty - rounded
        print(f"  stk={sid:>4} prod={pid} {pname[:35]:<35} {qty:.3f} -> {rounded} (delta {diff:+.3f})")

    # 2) Sof kg mahsulotlar
    print(f"\n--- 2. Sof kg mahsulotlar unit ko'chirish ({len(KG_PRODUCTS)} ta) ---")
    for pid in KG_PRODUCTS:
        cur.execute("SELECT id, name, unit_id, is_active FROM products WHERE id=?", (pid,))
        p = cur.fetchone()
        if not p:
            continue
        cur_unit = "ta" if p[2] == ta_id else ("kg" if p[2] == kg_id else f"id={p[2]}")
        active = "active" if p[3] else "inactive"
        action = "→ kg" if p[2] == ta_id else "(allaqachon kg)"
        print(f"  prod={pid} {p[1]:<25} ({active}, hozir={cur_unit}) {action}")

    if dry:
        print("\n(--apply bilan ishga tushiring)")
        conn.close()
        return 0

    # APPLY
    print("\n=== APPLY rejimi ===")
    print("Backup yaratamoqda...")
    backup = ROOT / "backups" / f"pre_dona_kg_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup.parent.mkdir(exist_ok=True)
    bk = sqlite3.connect(str(backup))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup.name} ({backup.stat().st_size / 1024 / 1024:.1f} MB)")

    # 1) Stock round + audit movement
    now = datetime.now().isoformat(sep=" ")
    fixed_stocks = 0
    for sid, wid, pid, pname, qty in fractional_stocks:
        rounded = round(qty)
        diff = rounded - qty
        note = f"[Donalik kasr round] {qty:.3f} -> {rounded}"
        cur.execute("UPDATE stocks SET quantity=?, updated_at=? WHERE id=?",
                    (float(rounded), now, sid))
        cur.execute("""
            INSERT INTO stock_movements
              (stock_id, warehouse_id, product_id, operation_type, document_type,
               document_id, document_number, quantity_change, quantity_after, user_id, note, created_at)
            VALUES (?, ?, ?, 'adjustment', 'StockAdjustmentDoc', 0, 'DONA-FIX-20260510',
                    ?, ?, NULL, ?, ?)
        """, (sid, wid, pid, float(diff), float(rounded), note, now))
        fixed_stocks += 1
    print(f"\n1. Stock round: {fixed_stocks} ta tuzatildi (audit movement bilan)")

    # 2) Unit ko'chirish
    moved = 0
    for pid in KG_PRODUCTS:
        r = cur.execute("UPDATE products SET unit_id=? WHERE id=? AND unit_id=?", (kg_id, pid, ta_id))
        if r.rowcount > 0:
            moved += r.rowcount
    print(f"2. KG mahsulotlar unit ko'chirildi: {moved} ta (dona -> kg)")

    conn.commit()

    # Tasdiq
    cur.execute(f"""
        SELECT COUNT(*) FROM stocks s
        JOIN products p ON p.id = s.product_id
        WHERE p.unit_id = {ta_id}
          AND ABS(s.quantity - ROUND(s.quantity)) > 0.001
          AND s.product_id NOT IN ({','.join(str(x) for x in KG_PRODUCTS)})
    """)
    remaining = cur.fetchone()[0]
    print(f"\nTasdiq: kasrli donalik stock qoldi: {remaining} ta (kutilgan: 0)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
