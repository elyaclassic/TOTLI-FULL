"""
Baza faylini nusxalash (backup) — totli_holva.db.
"""
import os
import shutil
from datetime import datetime

# Baza fayli (database.py dagi path bilan bir xil)
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_root, "totli_holva.db")
BACKUP_DIR = os.path.join(_root, "backups")


def do_backup(subdir: str = "") -> str:
    """
    totli_holva.db ni backups/ papkaga vaqt belgisi bilan nusxalaydi.
    subdir: ixtiyoriy past papka (masalan "daily").
    Qaytadi: yaratilgan faylning to'liq yo'li.
    """
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f"Baza fayli topilmadi: {DB_PATH}")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if subdir:
        dest_dir = os.path.join(BACKUP_DIR, subdir)
        os.makedirs(dest_dir, exist_ok=True)
    else:
        dest_dir = BACKUP_DIR
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"totli_holva_{stamp}.db"
    dest_path = os.path.join(dest_dir, name)
    shutil.copy2(DB_PATH, dest_path)
    return dest_path


def cleanup_old_backups(keep_count: int = 30, subdir: str = "") -> int:
    """
    Eski backup fayllarini o'chiradi (eng yangi keep_count ta qoladi).
    Qaytadi: o'chirilgan fayllar soni.
    """
    target = os.path.join(BACKUP_DIR, subdir) if subdir else BACKUP_DIR
    if not os.path.isdir(target):
        return 0
    files = [
        os.path.join(target, f)
        for f in os.listdir(target)
        if f.endswith(".db") and f.startswith("totli_holva_")
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    removed = 0
    for p in files[keep_count:]:
        try:
            os.remove(p)
            removed += 1
        except Exception:
            pass
    return removed
