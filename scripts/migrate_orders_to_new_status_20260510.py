"""Mavjud orderlarning statusini yangi nomenklaturaga ko'chirish.

Bosqich 1: --dry-run (default) — faqat ro'yxatni ko'rsatadi
Bosqich 2: --apply — backup yaratadi, UPDATE'lar bajariladi

Strategiya:
- 'completed' → 'delivered' (avtomatik)
- 'confirmed' Delivery 'delivered' bo'lgan → 'delivered'
- 'confirmed' Delivery 'pending' bo'lgan → 'out_for_delivery', delivery_date = order.date
- 'confirmed' Delivery yo'q → SO'RAYDI (har birini ko'rsatadi)
- 'draft', 'waiting_production' → o'zgarmaydi
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
    dry = "--apply" not in argv
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print("=" * 70)
    print("ORDER STATUS MIGRATSIYA — 2026-05-10")
    print(f"Rejim: {'DRY-RUN (faqat ko' + chr(39) + 'rsatish)' if dry else 'APPLY (UPDATE bajariladi)'}")
    print("=" * 70)

    cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
    print("\nHozirgi status taqsimot:")
    for status, count in cur.fetchall():
        print(f"  {status or '(NULL)':<25} {count:>6}")

    cur.execute("""
        SELECT o.id, o.number, o.status, o.date, o.partner_id, o.total,
               (SELECT d.status FROM deliveries d WHERE d.order_id = o.id LIMIT 1) AS delivery_status
        FROM orders o
        WHERE o.status IN ('confirmed', 'completed')
        ORDER BY o.id
    """)
    rows = cur.fetchall()

    completed_to_delivered = []
    confirmed_with_delivered = []
    confirmed_with_pending = []
    confirmed_no_delivery = []

    for row in rows:
        oid, num, status, _, _, _, dstatus = row
        if status == "completed":
            completed_to_delivered.append(oid)
        elif status == "confirmed":
            if dstatus == "delivered":
                confirmed_with_delivered.append(oid)
            elif dstatus in ("pending", "in_progress"):
                confirmed_with_pending.append(oid)
            else:
                confirmed_no_delivery.append(row)

    print(f"\nMigratsiya rejasi:")
    print(f"  completed → delivered: {len(completed_to_delivered)} ta")
    print(f"  confirmed (Delivery=delivered) → delivered: {len(confirmed_with_delivered)} ta")
    print(f"  confirmed (Delivery=pending/in_progress) → out_for_delivery: {len(confirmed_with_pending)} ta")
    print(f"  confirmed (Delivery yo'q): {len(confirmed_no_delivery)} ta — QO'LDA hal qilish")

    if confirmed_no_delivery:
        print("\nDelivery yo'q confirmed orderlar (oxirgi 10 ta):")
        for oid, num, _, dt, pid, tot, _ in confirmed_no_delivery[-10:]:
            print(f"  id={oid} {num} sana={dt} partner={pid} total={tot}")

    if dry:
        print("\n(--apply bilan ishga tushiring)")
        conn.close()
        return 0

    print("\nBackup yaratamoqda...")
    backup = ROOT / "backups" / f"pre_status_migrate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup.parent.mkdir(exist_ok=True)
    bk = sqlite3.connect(str(backup))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup.name}")

    if completed_to_delivered:
        cur.executemany("UPDATE orders SET status='delivered' WHERE id=?",
                       [(oid,) for oid in completed_to_delivered])
    if confirmed_with_delivered:
        cur.executemany("UPDATE orders SET status='delivered' WHERE id=?",
                       [(oid,) for oid in confirmed_with_delivered])
    if confirmed_with_pending:
        cur.executemany(
            "UPDATE orders SET status='out_for_delivery', delivery_date=DATE(date) WHERE id=?",
            [(oid,) for oid in confirmed_with_pending])
    conn.commit()
    print(f"\nUPDATE bajarildi: {len(completed_to_delivered) + len(confirmed_with_delivered) + len(confirmed_with_pending)} ta")
    print("Delivery yo'q confirmed orderlar o'zgarmadi — qo'lda hal qiling")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
