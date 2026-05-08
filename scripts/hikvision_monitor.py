"""TOTLI BI — Hikvision health monitor (O11 audit fix)

Hikvision domofon/qurilma javob bermasa Telegram orqali ogohlantirish.
Har 10 daq Task Scheduler chaqiradi (TOTLI Hikvision Monitor).

Mantiq:
- Qurilma test_connection() qiladi
- Muvaffaqiyatli bo'lsa: data/hikvision_state.json'ga last_ok_at yoziladi
- Muvaffaqiyatsiz bo'lsa: last_ok_at >20 daq oldin va oxirgi alert >1 soat oldin
  bo'lsa Telegram'ga DOWN xabar yuboriladi
- Qayta tiklansa: "tiklandi" xabari
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "hikvision_monitor.log"
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "data" / "hikvision_state.json"
OWNER_ID = "1340383182"

DOWN_THRESHOLD_MIN = 20
ALERT_COOLDOWN_MIN = 60


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
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    print(line, end="")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def send_telegram(text: str) -> None:
    token = load_env("CLAUDE_BOT_TOKEN")
    if not token:
        log("CLAUDE_BOT_TOKEN topilmadi — xabar yuborilmadi")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": OWNER_ID,
        "text": text[:3500],
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        log(f"Telegram xato: {e}")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def main() -> int:
    host = load_env("HIKVISION_HOST") or "192.168.1.199"
    port = int(load_env("HIKVISION_PORT") or "443")
    username = load_env("HIKVISION_USERNAME") or "admin"
    password = load_env("HIKVISION_PASSWORD") or ""

    try:
        from app.utils.hikvision import HikvisionAPI
    except Exception as e:
        log(f"Import xato: {e}")
        return 1

    api = HikvisionAPI(host=host, port=port, username=username, password=password)
    now = datetime.now()
    state = load_state()
    was_down = state.get("is_down", False)
    last_alert_at = parse_dt(state.get("last_alert_at", ""))
    last_ok_at = parse_dt(state.get("last_ok_at", ""))

    is_ok = api.test_connection()

    if is_ok:
        state["last_ok_at"] = now.isoformat()
        state["is_down"] = False
        if was_down:
            down_for = "noma'lum"
            if last_ok_at:
                mins = int((now - last_ok_at).total_seconds() / 60)
                down_for = f"{mins} daq"
            send_telegram(
                f"✅ <b>Hikvision tiklandi</b>\n"
                f"Qurilma: {host}:{port}\n"
                f"O'chiq turgan: {down_for}\n"
                f"Vaqt: {now.strftime('%H:%M %d.%m')}"
            )
            log(f"RECOVERED: down for {down_for}")
        else:
            log(f"OK: {host}:{port}")
        save_state(state)
        return 0

    err = api._last_error or f"status={api._last_status}"
    log(f"DOWN: {host}:{port} — {err}")

    down_minutes = 0
    if last_ok_at:
        down_minutes = int((now - last_ok_at).total_seconds() / 60)

    should_alert = down_minutes >= DOWN_THRESHOLD_MIN
    if should_alert and last_alert_at:
        cooldown_passed = (now - last_alert_at).total_seconds() / 60 >= ALERT_COOLDOWN_MIN
        if not cooldown_passed:
            should_alert = False

    if not last_ok_at:
        state.setdefault("first_seen_down_at", state.get("first_seen_down_at") or now.isoformat())

    if should_alert:
        send_telegram(
            f"⚠️ <b>Hikvision javob bermayapti</b>\n"
            f"Qurilma: {host}:{port}\n"
            f"Oxirgi muvaffaqiyat: {last_ok_at.strftime('%H:%M %d.%m') if last_ok_at else 'noma''lum'}\n"
            f"O'chiq turibdi: {down_minutes} daq\n"
            f"Xato: {err[:200]}\n\n"
            f"Tabel hozir to'planmaydi. Tarmoq/qurilmani tekshiring."
        )
        state["last_alert_at"] = now.isoformat()
        log(f"ALERT yuborildi (down {down_minutes} daq)")

    state["is_down"] = True
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
