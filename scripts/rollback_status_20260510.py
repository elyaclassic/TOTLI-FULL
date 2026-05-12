"""Yetkazish kuni status migratsiyasini qaytarish (rollback).

Deploy'da xato bo'lsa ishlatiladi:
  delivered       -> completed
  out_for_delivery -> confirmed

delivery_date va dispatched_at ustunlari o'chirilmaydi (data sifatida qoladi —
keyingi kun re-deploy uchun zarar yo'q).

Bosqich 1: --dry-run (default) — faqat ko'rsatadi
Bosqich 2: --apply — backup yaratadi, UPDATE'lar bajariladi
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"
BACKUP_DIR = ROOT / "backups"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(argv):
    dry = "--apply" not in argv
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print("=" * 70)
    print("ORDER STATUS ROLLBACK — 2026-05-10 yetkazish kuni feature'ni qaytarish")
    print(f"Rejim: {'DRY-RUN (faqat ko' + chr(39) + 'rsatish)' if dry else 'APPLY (UPDATE bajariladi)'}")
    print("=" * 70)

    cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
    print("\nHozirgi status taqsimot:")
    for status, count in cur.fetchall():
        print(f"  {status or '(NULL)':<25} {count:>6}")

    cur.execute("SELECT COUNT(*) FROM orders WHERE status='delivered'")
    n_delivered = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders WHERE status='out_for_delivery'")
    n_out = cur.fetchone()[0]

    print("\nRollback rejasi:")
    print(f"  delivered -> completed: {n_delivered} ta")
    print(f"  out_for_delivery -> confirmed: {n_out} ta")
    print(f"  Jami: {n_delivered + n_out} ta UPDATE")
    print(f"\ndelivery_date va dispatched_at ustunlari saqlanadi (additive data).")

    if dry:
        print("\n(--apply bilan ishga tushiring)")
        conn.close()
        return 0

    if n_delivered + n_out == 0:
        print("\nQaytariladigan order yo'q. Chiqildi.")
        conn.close()
        return 0

    print("\nBackup yaratamoqda...")
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / f"pre_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    bk = sqlite3.connect(str(backup))
    conn.backup(bk)
    bk.close()
    print(f"Backup: {backup.relative_to(ROOT)}")

    cur.execute("UPDATE orders SET status='completed' WHERE status='delivered'")
    a1 = cur.rowcount
    cur.execute("UPDATE orders SET status='confirmed' WHERE status='out_for_delivery'")
    a2 = cur.rowcount
    conn.commit()

    print(f"\nUPDATE bajarildi:")
    print(f"  delivered -> completed: {a1} ta")
    print(f"  out_for_delivery -> confirmed: {a2} ta")
    print("\nServer'ni qayta ishga tushirishni unutmang (taskkill /IM python.exe /F + start.bat)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
