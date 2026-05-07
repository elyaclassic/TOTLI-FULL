"""TOTLI BI — off-site backup
Eng yangi DB backup'ni masofadagi joyga nusxalaydi (ikkinchi LAN PC, NAS, yoki cloud-mounted folder).

Konfiguratsiya (.env yoki environment):
- OFFSITE_BACKUP_PATH — masofa target katalog (UNC, lokal disk, mount-point)
   Misollar:
     \\\\OFFICE-PC2\\backups\\totli         (SMB share — boshqa LAN PC)
     E:\\totli_offsite                       (USB / external HDD)
     C:\\Yandex.Disk\\TOTLI                  (Yandex.Disk client mount)
- OFFSITE_RETENTION_DAYS — necha kunlik fayl saqlanadi (default 30)
- HEALTHCHECK_URL — muvaffaqiyat ping URL (Healthchecks.io)

Mantiq:
1. backups/live/ ichidagi eng yangi *.db.gz topiladi
2. OFFSITE_BACKUP_PATH/totli_holva_<sana>_offsite.db.gz ga nusxalanadi
3. Eskirgan fayllar (>RETENTION_DAYS) o'chiriladi
4. Healthcheck ping (agar URL bor bo'lsa)
5. Yordamchim botga muvaffaqiyat/xato xabar
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
LIVE_BACKUP_DIR = ROOT / "backups" / "live"
LOG_PATH = ROOT / "backup_offsite.log"
ENV_PATH = ROOT / ".env"
OWNER_ID = "1340383182"


def load_env(name: str) -> str:
    val = os.environ.get(name)
    if val:
        return val
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    print(line, end="")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def send_telegram(text: str) -> None:
    token = load_env("CLAUDE_BOT_TOKEN")
    if not token:
        return
    import urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": OWNER_ID,
        "text": text[:3500],
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception:
        pass


def find_latest_backup() -> Path:
    """backups/live/ dan eng yangi .db.gz qaytaradi."""
    if not LIVE_BACKUP_DIR.exists():
        raise FileNotFoundError(f"Live backup dir topilmadi: {LIVE_BACKUP_DIR}")
    files = sorted(LIVE_BACKUP_DIR.glob("*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"backups/live ichida .db.gz fayl yo'q")
    return files[0]


def verify_gzip(path: Path) -> bool:
    """Backup fayl gzip integrity testi."""
    try:
        with gzip.open(str(path), "rb") as f:
            while f.read(1024 * 1024):
                pass
        return True
    except Exception:
        return False


def cleanup_offsite(target_dir: Path, keep_days: int) -> int:
    """Eskirgan fayllarni o'chiradi."""
    if not target_dir.exists():
        return 0
    cutoff = time.time() - keep_days * 86400
    deleted = 0
    for f in target_dir.glob("totli_holva_*.db.gz"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted


def healthcheck_ping(url: str, success: bool = True) -> None:
    if not url:
        return
    if not success:
        url = url.rstrip("/") + "/fail"
    try:
        urllib.request.urlopen(url, timeout=10)
    except Exception:
        pass


def main() -> int:
    target_str = load_env("OFFSITE_BACKUP_PATH")
    if not target_str:
        log("ERROR: OFFSITE_BACKUP_PATH .env'da yoki environment'da o'rnatilmagan")
        send_telegram(
            "❌ <b>Off-site backup</b> sozlanmagan!\n\n"
            "OFFSITE_BACKUP_PATH ni .env'ga qo'shing:\n"
            "<code>OFFSITE_BACKUP_PATH=\\\\OFFICE-PC2\\backups\\totli</code>\n"
            "yoki USB: <code>E:\\totli_offsite</code>"
        )
        return 1

    retention = int(load_env("OFFSITE_RETENTION_DAYS") or "30")
    healthcheck = load_env("HEALTHCHECK_URL")

    target_dir = Path(target_str)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"ERROR: target katalogi yaratib bo'lmadi: {target_dir}: {e}")
        send_telegram(f"❌ Off-site backup: target katalogi mavjud emas\n<code>{target_dir}</code>\n{e}")
        healthcheck_ping(healthcheck, success=False)
        return 1

    try:
        latest = find_latest_backup()
    except FileNotFoundError as e:
        log(f"ERROR: {e}")
        send_telegram(f"❌ Off-site backup: {e}")
        healthcheck_ping(healthcheck, success=False)
        return 1

    if not verify_gzip(latest):
        log(f"ERROR: source fayl gzip buzilgan: {latest.name}")
        send_telegram(f"❌ Off-site backup: source corrupt {latest.name}")
        healthcheck_ping(healthcheck, success=False)
        return 1

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target_file = target_dir / f"totli_holva_{timestamp}_offsite.db.gz"

    try:
        shutil.copy2(latest, target_file)
    except Exception as e:
        log(f"ERROR: nusxalash xato: {e}")
        send_telegram(f"❌ Off-site backup nusxalashda xato: {e}")
        healthcheck_ping(healthcheck, success=False)
        return 1

    if not verify_gzip(target_file):
        log(f"ERROR: nusxalangan fayl gzip buzilgan: {target_file.name}")
        send_telegram(f"❌ Off-site backup: target corrupt {target_file.name}")
        healthcheck_ping(healthcheck, success=False)
        return 1

    size_mb = target_file.stat().st_size / 1024 / 1024
    deleted = cleanup_offsite(target_dir, retention)
    log(f"OK {target_file.name} ({size_mb:.1f} MB), eskirgan o'chirildi: {deleted}")

    healthcheck_ping(healthcheck, success=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
