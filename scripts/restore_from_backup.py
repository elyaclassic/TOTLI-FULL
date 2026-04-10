"""
Backup'dan DB ni qaytarish.

MUHIM: Bu skriptni ishlatishdan oldin uvicorn SERVERNI TO'XTATING!
Aks holda DB jonli yozish paytida buziladi.

Foydalanish:
    python scripts/restore_from_backup.py <backup_fayl.db.gz>
    python scripts/restore_from_backup.py --latest     # eng so'nggi backup
    python scripts/restore_from_backup.py --list       # mavjud backuplar ro'yxati
"""
import gzip
import os
import shutil
import sqlite3
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_ROOT, "totli_holva.db")
BACKUP_ROOT = r"D:\TOTLI_BI_BACKUPS"
LIVE_DIR = os.path.join(BACKUP_ROOT, "live")


def list_backups():
    if not os.path.isdir(LIVE_DIR):
        print(f"Backup papkasi yo'q: {LIVE_DIR}")
        return []
    files = []
    for name in sorted(os.listdir(LIVE_DIR), reverse=True):
        if name.endswith(".db.gz"):
            path = os.path.join(LIVE_DIR, name)
            size_mb = os.path.getsize(path) / 1024 / 1024
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            files.append((path, size_mb, mtime))
    return files


def cmd_list():
    files = list_backups()
    if not files:
        print("Backup topilmadi.")
        return
    print(f"\nJami {len(files)} ta backup (yangisidan eskisiga):\n")
    for path, size, mtime in files:
        print(f"  {mtime.strftime('%Y-%m-%d %H:%M:%S')}  {size:6.2f} MB  {os.path.basename(path)}")


def cmd_restore(backup_path: str):
    if not os.path.isfile(backup_path):
        print(f"XATO: backup topilmadi: {backup_path}")
        sys.exit(1)

    if not backup_path.endswith(".db.gz"):
        print("XATO: backup .db.gz formatida bo'lishi kerak")
        sys.exit(1)

    # 1) Xavfsizlik: jonli DB ni saqlab qo'yish
    safety_name = f"totli_holva_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    safety_path = os.path.join(BACKUP_ROOT, safety_name)
    os.makedirs(BACKUP_ROOT, exist_ok=True)

    print(f"\n1/4  Jonli DB xavfsizlik nusxasi: {safety_name}")
    if os.path.isfile(DB_PATH):
        shutil.copy2(DB_PATH, safety_path)
        print(f"     OK ({os.path.getsize(safety_path) / 1024 / 1024:.2f} MB)")
    else:
        print("     OGOHLANTIRISH: jonli DB topilmadi")

    # 2) WAL/SHM fayllarini o'chirish (eski holatdan)
    print(f"\n2/4  WAL/SHM fayllarni tozalash")
    for ext in ("-wal", "-shm"):
        side = DB_PATH + ext
        if os.path.exists(side):
            try:
                os.remove(side)
                print(f"     o'chirildi: {os.path.basename(side)}")
            except Exception as e:
                print(f"     o'chirib bo'lmadi: {side}: {e}")

    # 3) Gzip ochib, DB ga yozish
    print(f"\n3/4  Backup ochilmoqda: {os.path.basename(backup_path)}")
    try:
        with gzip.open(backup_path, "rb") as f_in:
            with open(DB_PATH, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
        print(f"     OK ({os.path.getsize(DB_PATH) / 1024 / 1024:.2f} MB)")
    except Exception as e:
        print(f"     XATO: {e}")
        print(f"\nOrtga qaytarish: {safety_path} ni qo'lda totli_holva.db ga ko'chiring")
        sys.exit(1)

    # 4) Integrity check
    print(f"\n4/4  integrity_check")
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            r = conn.execute("PRAGMA integrity_check").fetchone()
            print(f"     {r[0]}")
            if r[0] != "ok":
                print("\nXATO: integrity_check 'ok' emas. Ortga qaytarish:")
                print(f"  copy \"{safety_path}\" \"{DB_PATH}\"")
                sys.exit(1)
        finally:
            conn.close()
    except Exception as e:
        print(f"     XATO: {e}")
        sys.exit(1)

    print(f"\n✓ MUVAFFAQIYATLI QAYTARILDI")
    print(f"  Jonli DB: {DB_PATH}")
    print(f"  Xavfsizlik nusxasi: {safety_path}")
    print(f"\nEndi uvicorn serverni qayta ishga tushiring.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--list":
        cmd_list()
        return

    if arg == "--latest":
        files = list_backups()
        if not files:
            print("Backup topilmadi.")
            sys.exit(1)
        backup_path = files[0][0]
        print(f"Eng so'nggi backup: {os.path.basename(backup_path)}")
    else:
        backup_path = arg
        if not os.path.isabs(backup_path):
            # Nisbiy yo'l — LIVE_DIR dan izlash
            candidate = os.path.join(LIVE_DIR, backup_path)
            if os.path.isfile(candidate):
                backup_path = candidate

    # Tasdiqlash so'rash
    print(f"\nDIQQAT: Bu amal jonli DB ni QAYTA YOZADI!")
    print(f"Backup: {backup_path}")
    print(f"Manzil: {DB_PATH}")
    print(f"\nUvicorn server to'xtatilganligiga ishonchmisiz? (ha/yo'q): ", end="")
    ans = input().strip().lower()
    if ans not in ("ha", "yes", "y"):
        print("Bekor qilindi.")
        sys.exit(0)

    cmd_restore(backup_path)


if __name__ == "__main__":
    main()
