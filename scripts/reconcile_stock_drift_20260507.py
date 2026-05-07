"""Stock drift reconciliation — 2026-05-07 audit
Har drifted stock uchun retroactive InitialBalance movement yaratadi.

Mantiq:
- diff = stock.quantity - sum(stock_movements.quantity_change)
- agar diff != 0: yangi movement (document_type='InitialBalance')
  yaratiladi, quantity_change=diff, vaqti birinchi movement'dan oldin

Ishlatish:
    python scripts/reconcile_stock_drift_20260507.py --dry-run    # ko'rish
    python scripts/reconcile_stock_drift_20260507.py --apply      # bajarish
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(argv):
    dry_run = "--dry-run" in argv
    apply = "--apply" in argv
    if not (dry_run or apply):
        print("Ishlatish: --dry-run yoki --apply")
        return 1
    if apply and dry_run:
        print("Faqat bittasi: --dry-run YOKI --apply")
        return 1

    if not DB_PATH.exists():
        print(f"DB topilmadi: {DB_PATH}")
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Drifted stocks ro'yxati
    cur.execute("""
        SELECT s.id,
               s.warehouse_id,
               s.product_id,
               s.quantity,
               COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm WHERE sm.stock_id=s.id), 0) as sum_mv,
               (SELECT MIN(sm.created_at) FROM stock_movements sm WHERE sm.stock_id=s.id) as first_mv
        FROM stocks s
        WHERE ABS(s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm WHERE sm.stock_id=s.id), 0)) > 0.01
        ORDER BY s.id
    """)
    drifted = cur.fetchall()

    print(f"=== {len(drifted)} ta drifted stock topildi ===")
    if dry_run:
        print("DRY RUN — hech narsa o'zgarmaydi\n")

    total_diff = 0
    new_movements = []

    for stock_id, warehouse_id, product_id, qty, sum_mv, first_mv in drifted:
        diff = round(float(qty or 0) - float(sum_mv or 0), 4)
        if abs(diff) <= 0.01:
            continue
        total_diff += diff

        # InitialBalance vaqti: birinchi movement'dan 1 sek oldin (yoki 2026-03-01)
        if first_mv:
            try:
                first_dt = datetime.strptime(first_mv[:19], "%Y-%m-%d %H:%M:%S")
                ib_dt = first_dt - timedelta(seconds=1)
            except (ValueError, TypeError):
                ib_dt = datetime(2026, 3, 1, 0, 0, 0)
        else:
            ib_dt = datetime(2026, 3, 1, 0, 0, 0)

        new_movements.append({
            "stock_id": stock_id,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity_change": diff,
            "quantity_after": diff,
            "created_at": ib_dt.isoformat(sep=" "),
        })

    print(f"Yangi InitialBalance movements: {len(new_movements)}")
    print(f"Total diff (jami balans tiklanadigan): {total_diff:+,.2f}")
    print()

    # Sample: 5 ta misol
    print("=== Sample (5 ta) ===")
    for mv in new_movements[:5]:
        cur.execute("SELECT name FROM products WHERE id=?", (mv["product_id"],))
        prod = cur.fetchone()
        prod_name = prod[0] if prod else f"prod_{mv['product_id']}"
        cur.execute("SELECT name FROM warehouses WHERE id=?", (mv["warehouse_id"],))
        wh = cur.fetchone()
        wh_name = wh[0] if wh else f"wh_{mv['warehouse_id']}"
        print(f"  stock_id={mv['stock_id']:4} {wh_name[:18]:18} {prod_name[:30]:30} change={mv['quantity_change']:>+10.2f} dt={mv['created_at']}")

    if dry_run:
        print("\n(--apply bilan ishga tushirib ko'ring)")
        conn.close()
        return 0

    # APPLY
    print("\n=== APPLY rejimi ===")
    print("Backup yaratamoqda...")
    backup_path = ROOT / "backups" / f"pre_reconcile_drift_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path.parent.mkdir(exist_ok=True)
    bk = sqlite3.connect(str(backup_path))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup_path.name} ({backup_path.stat().st_size / 1024 / 1024:.1f} MB)")

    print(f"Insert qilmoqda: {len(new_movements)} ta yangi movement...")
    cur.executemany("""
        INSERT INTO stock_movements
        (stock_id, warehouse_id, product_id, operation_type, document_type, document_id, document_number,
         quantity_change, quantity_after, user_id, note, created_at)
        VALUES (:stock_id, :warehouse_id, :product_id,
                'initial_balance', 'InitialBalance', 0, 'INIT-BALANCE-RETRO',
                :quantity_change, :quantity_after, NULL,
                '[BOSHLANGICH QOLDIQ — retroactive 2026-05-07]',
                :created_at)
    """, new_movements)
    conn.commit()
    print("OK — INSERT bajarildi")

    # Verify: integrity check
    print("\n=== TASDIQ — qayta drift tekshiruvi ===")
    cur.execute("""
        SELECT COUNT(*) FROM stocks s
        WHERE ABS(s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm WHERE sm.stock_id=s.id), 0)) > 0.01
    """)
    remaining = cur.fetchone()[0]
    print(f"Qoldi drift: {remaining} ta (oldin {len(drifted)})")
    if remaining == 0:
        print("✅ HAMMASI TOZA")
    else:
        print(f"⚠ {remaining} ta qoldi — qo'shimcha tekshirish kerak")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
