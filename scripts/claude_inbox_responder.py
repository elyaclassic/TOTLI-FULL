"""Telegram inbox -> Claude CLI -> Yordamchim bot bridge.

Task Scheduler tomonidan har 1 daqiqada chaqiriladi (`elya_` user hisobida,
chunki `claude.cmd` va Anthropic OAuth credentials shu profilda).

Oqim:
1. `app/bot/data/inbox.jsonl` dan `responder_last_seen.txt` dan keyingi
   xabarlarni o'qish.
2. Hammasini bitta promptga birlashtirib (batch) `claude -p ... --continue`
   ga uzatish — `--continue` tufayli oldingi suhbat konteksti saqlanib qoladi
   ("yodda oluvchi" Telegram chat).
3. Javobni `/api/internal/notify-owner` ga POST qilib Yordamchim botga
   yuborish (xuddi `claude_telegram_sync.py --stop` qiladigan kabi).
4. Last-seen marker yangilanadi.

Lock fayl bilan ikkita instance parallel ishlamasligi ta'minlanadi.
Ishlash muvaffaqiyatsiz bo'lsa, last-seen yangilanmaydi va keyingi chaqiriqda
qaytariladi.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "app" / "bot" / "data"
INBOX = INBOX_DIR / "inbox.jsonl"
LAST_SEEN = INBOX_DIR / "responder_last_seen.txt"
LOCK = INBOX_DIR / "responder.lock"
LOG = ROOT / "watchdog.log"
# Responder uchun alohida cwd — shu yerda --continue oldingi javoblar bilan
# bog'lanadi va loyiha Claude Code sessiyalari bilan kesishmaydi.
RESPONDER_WORKDIR = INBOX_DIR / "responder_workdir"
NOTIFY_URL = os.environ.get(
    "CLAUDE_NOTIFY_URL",
    "http://10.243.165.156:8080/api/internal/notify-owner",
)
CLAUDE_CMD = os.environ.get(
    "CLAUDE_CLI", r"C:\Users\elya_\AppData\Roaming\npm\claude.cmd"
)
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "180"))
LOCK_TIMEOUT_MIN = 15
MAX_BATCH = 10


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [responder] {msg}\n"
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def acquire_lock() -> bool:
    if LOCK.exists():
        age_min = (time.time() - LOCK.stat().st_mtime) / 60.0
        if age_min < LOCK_TIMEOUT_MIN:
            return False
        log(f"stale lock ({age_min:.1f} min) — tozalandi")
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock() -> None:
    try:
        LOCK.unlink()
    except FileNotFoundError:
        pass


def get_last_seen() -> str:
    try:
        return LAST_SEEN.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""


def set_last_seen(msg_id: str) -> None:
    LAST_SEEN.write_text(msg_id, encoding="utf-8")


def read_unread() -> list[dict]:
    if not INBOX.exists():
        return []
    last_seen = get_last_seen()
    out: list[dict] = []
    with INBOX.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(rec.get("id", "")) > last_seen:
                out.append(rec)
    out.sort(key=lambda r: str(r.get("id", "")))
    return out


def build_prompt(msgs: list[dict]) -> str:
    parts = ["Yordamchim bot orqali yangi xabar(lar) keldi:"]
    for m in msgs[-MAX_BATCH:]:
        ts = m.get("ts", "")
        text = (m.get("text") or "").strip()
        if m.get("kind") == "photo":
            photo = m.get("photo", "")
            text = f"[FOTO yuborildi: {photo}] {text}".strip()
        parts.append(f"[{ts}] {text}")
    parts.append(
        "\nIltimos, foydalanuvchiga to'g'ridan-to'g'ri o'zbek tilida qisqa "
        "javob ber. Tool chaqiriqlarini minimum tut."
    )
    return "\n".join(parts)


def _run_claude(args: list[str], prompt: str) -> subprocess.CompletedProcess:
    """Promptni stdin orqali uzatadi — Windows cmd argument newline buzilishini chetlab o'tadi."""
    return subprocess.run(
        args,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
        encoding="utf-8",
        errors="replace",
        cwd=str(RESPONDER_WORKDIR),
    )


def call_claude(prompt: str) -> str:
    RESPONDER_WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        result = _run_claude([CLAUDE_CMD, "-p", "--continue"], prompt)
    except FileNotFoundError:
        log(f"claude CLI topilmadi: {CLAUDE_CMD}")
        return ""
    except subprocess.TimeoutExpired:
        log(f"claude timeout ({CLAUDE_TIMEOUT}s)")
        return ""
    except Exception as e:
        log(f"claude xato: {e}")
        return ""

    if result.returncode != 0:
        stderr_short = (result.stderr or "")[:200]
        log(f"claude exit={result.returncode} stderr={stderr_short}")
        if "no" in (result.stderr or "").lower() and "session" in (result.stderr or "").lower():
            log("--continue muvaffaqiyatsiz, yangi session bilan urinish")
            try:
                result = _run_claude([CLAUDE_CMD, "-p"], prompt)
                if result.returncode != 0:
                    return ""
            except Exception as e:
                log(f"fallback claude xato: {e}")
                return ""
        else:
            return ""

    return (result.stdout or "").strip()


def post_to_telegram(text: str) -> bool:
    if len(text) > 3500:
        text = text[:3500] + "\n[uzun javob qisqartirildi]"
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        NOTIFY_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        log(f"notify HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return False
    except Exception as e:
        log(f"notify xato: {e}")
        return False


def main() -> int:
    msgs = read_unread()
    if not msgs:
        return 0

    if not acquire_lock():
        log(f"lock band ({len(msgs)} ta o'qilmagan kutmoqda)")
        return 0

    try:
        log(f"claude ga uzatilmoqda: {len(msgs)} ta xabar")
        prompt = build_prompt(msgs)
        response = call_claude(prompt)

        if not response:
            log("claude bo'sh javob qaytardi — qayta urinamiz keyingi safar")
            return 0

        if not post_to_telegram(response):
            log("Telegramga yuborishda xato — last_seen yangilanmaydi")
            return 0

        latest_id = max(str(m.get("id", "")) for m in msgs)
        set_last_seen(latest_id)
        log(f"javob yuborildi ({len(response)} chars), last_seen={latest_id}")
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
