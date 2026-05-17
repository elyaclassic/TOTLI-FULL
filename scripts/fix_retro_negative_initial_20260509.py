"""Fix retroactive InitialBalance with negative quantity_change.

Bug: reconcile_stock_drift_20260507.py manfiy diff uchun ham retroaktiv
InitialBalance yaratardi → eski sanalardagi vaqt-aware qoldiq tekshiruvini
buzdi (Xurmo djem -2.5, va boshqalar).

Fix: shu manfiy yozuvlarning created_at ni bugunga ko'chirish.
- Bugungi stock.quantity o'zgarmaydi (sum_change o'zgarmaydi)
- Eski sanada chain endi -2.5 dan boshlamaydi
- Production yakunlash (vaqt-aware shortage check) to'g'ri ishlaydi
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


def main(argv):
    dry = "--dry-run" in argv
    apply = "--apply" in argv
    if not (dry or apply):
        print("Ishlatish: --dry-run yoki --apply")
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
        SELECT id, stock_id, product_id, warehouse_id, quantity_change, created_at
        FROM stock_movements
        WHERE document_number='INIT-BALANCE-RETRO' AND quantity_change < 0
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f"=== {len(rows)} ta manfiy retroaktiv InitialBalance ===")
    total = sum(float(r[4] or 0) for r in rows)
    print(f"Jami: {total:+,.2f}")

    if dry:
        print("\nSample (5 ta):")
        for r in rows[:5]:
            print(f"  id={r[0]} stock={r[1]} prod={r[2]} ch={r[4]:+.3f} dt={r[5]}")
        print("\n--apply bilan ishga tushiring")
        conn.close()
        return 0

    print("\nBackup yaratamoqda...")
    backup = ROOT / "backups" / f"pre_retro_neg_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup.parent.mkdir(exist_ok=True)
    bk = sqlite3.connect(str(backup))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup.name}")

    # created_at ni bugunga ko'chirish + note yangilash
    now = datetime.now().isoformat(sep=" ")
    cur.execute("""
        UPDATE stock_movements
        SET created_at = ?,
            note = '[Drift balanslash — manfiy: bugunga ko''chirildi 2026-05-09]'
        WHERE document_number='INIT-BALANCE-RETRO' AND quantity_change < 0
    """, (now,))
    affected = cur.rowcount
    conn.commit()
    print(f"Yangilandi: {affected} ta movement, created_at = {now}")

    # Tasdiq: drift hali ham 0
    cur.execute("""
        SELECT COUNT(*) FROM stocks s
        WHERE ABS(s.quantity - COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm WHERE sm.stock_id=s.id), 0)) > 0.01
    """)
    drift = cur.fetchone()[0]
    print(f"Drift hozir: {drift} ta (kutilgan: 0)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
