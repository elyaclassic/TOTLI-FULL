"""
Jonli (live) SQLite backup — har 5 daqiqada chaqiriladi.

Xususiyatlari:
- sqlite3.Connection.backup() — WAL-safe online backup
- gzip siqish
- Retention: 2 soatdan eskilari avtomatik o'chiriladi
- Fail bo'lsa Telegram alert (@elya_classic)
- Lock file — parallel chaqiruvlarni oldini oladi

Qo'lda sinash: python scripts/backup_live.py
"""
import os
import sys
import gzip
import shutil
import sqlite3
import traceback
from datetime import datetime, timedelta

# Loyiha ildiziga chiqish (scripts/ dan bir yuqori)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

DB_PATH = os.path.join(_ROOT, "totli_holva.db")
BACKUP_ROOT = r"D:\TOTLI_BI_BACKUPS"
LIVE_DIR = os.path.join(BACKUP_ROOT, "live")
LOCK_FILE = os.path.join(BACKUP_ROOT, ".backup_live.lock")
RETENTION_MINUTES = 125  # 2 soat + 5 daqiqa buffer
LOCK_STALE_SECONDS = 120  # 2 daqiqadan katta lock eski deb hisoblanadi


def _log(msg: str):
    print(f"[backup_live] {datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


def _write_error_log(tb: str):
    try:
        with open(os.path.join(_ROOT, "server_error.log"), "a", encoding="utf-8") as f:
            f.write(f"\n--- [backup_live] {datetime.now().isoformat()} ---\n{tb}\n")
    except Exception:
        pass


def _acquire_lock() -> bool:
    """Lock file yaratadi. Agar eski lock bo'lsa — ustidan yozadi."""
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    if os.path.exists(LOCK_FILE):
        try:
            age = (datetime.now().timestamp() - os.path.getmtime(LOCK_FILE))
            if age < LOCK_STALE_SECONDS:
                return False
            _log(f"eski lock topildi ({age:.0f}s), ustidan yoziladi")
        except Exception:
            pass
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
        return True
    except Exception:
        return False


def _release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def _alert_telegram(message: str):
    """Telegram @elya_classic ga xato ogohlantirishi."""
    try:
        from app.bot.config import REALTIME_CHAT_IDS
        from app.bot.services.notifier import _send_to_chats_sync
        text = f"🚨 <b>BACKUP FAIL</b>\n\n{message}\n\n<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        _send_to_chats_sync(text, REALTIME_CHAT_IDS)
    except Exception as e:
        _log(f"telegram alert fail: {e}")


def _do_sqlite_backup(src: str, dest_tmp: str):
    """sqlite3 online backup API. WAL-safe, jonli yozish davomida."""
    src_conn = sqlite3.connect(src)
    try:
        dest_conn = sqlite3.connect(dest_tmp)
        try:
            with dest_conn:
                src_conn.backup(dest_conn, pages=0)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _gzip_file(src: str, dest_gz: str):
    """Faylni gzip bilan siqib dest_gz ga yozadi. Manba fayl o'chirilmaydi."""
    with open(src, "rb") as f_in:
        with gzip.open(dest_gz, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)


def _cleanup_old_backups() -> int:
    """RETENTION_MINUTES dan eski fayllarni o'chiradi."""
    if not os.path.isdir(LIVE_DIR):
        return 0
    cutoff = datetime.now() - timedelta(minutes=RETENTION_MINUTES)
    removed = 0
    for name in os.listdir(LIVE_DIR):
        if not name.endswith(".db.gz"):
            continue
        path = os.path.join(LIVE_DIR, name)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                os.remove(path)
                removed += 1
        except Exception:
            continue
    return removed


def run_live_backup(send_alert_on_fail: bool = True) -> dict:
    """
    Asosiy funksiya — 1 ta backup yaratadi + eskilarini tozalaydi.
    Qaytaradi: {"ok": bool, "path": str, "size_mb": float, "removed": int, "error": str}
    """
    result = {"ok": False, "path": None, "size_mb": 0.0, "removed": 0, "error": None}

    if not _acquire_lock():
        result["error"] = "lock band — oldingi backup hali tugamagan"
        _log(result["error"])
        return result

    try:
        if not os.path.isfile(DB_PATH):
            raise FileNotFoundError(f"DB topilmadi: {DB_PATH}")

        os.makedirs(LIVE_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        tmp_db = os.path.join(LIVE_DIR, f".{stamp}.db.tmp")
        final_gz = os.path.join(LIVE_DIR, f"{stamp}.db.gz")

        # 1) Online sqlite backup → tmp
        _do_sqlite_backup(DB_PATH, tmp_db)

        # 2) Gzip → final
        _gzip_file(tmp_db, final_gz)

        # 3) tmp ni o'chirish
        try:
            os.remove(tmp_db)
        except Exception:
            pass

        # 4) Eskilarini tozalash
        removed = _cleanup_old_backups()

        size_mb = os.path.getsize(final_gz) / (1024 * 1024)
        result.update({
            "ok": True,
            "path": final_gz,
            "size_mb": round(size_mb, 2),
            "removed": removed,
        })
        _log(f"OK {os.path.basename(final_gz)} ({size_mb:.2f} MB), eski o'chirilgan: {removed}")

    except Exception as e:
        tb = traceback.format_exc()
        result["error"] = str(e)
        _log(f"FAIL: {e}")
        _write_error_log(tb)
        if send_alert_on_fail:
            _alert_telegram(f"Jonli backup bajarilmadi: <code>{str(e)[:300]}</code>")
    finally:
        _release_lock()

    return result


if __name__ == "__main__":
    r = run_live_backup(send_alert_on_fail=False)
    if r["ok"]:
        print(f"OK: {r['path']} ({r['size_mb']} MB), o'chirildi: {r['removed']}")
        sys.exit(0)
    else:
        print(f"FAIL: {r['error']}")
        sys.exit(1)
