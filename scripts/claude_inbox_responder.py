"""Telegram inbox -> Claude CLI -> Yordamchim bot bridge.

Task Scheduler tomonidan har 1 daqiqada chaqiriladi. Loyihaning to'liq
konteksti (CLAUDE.md + memory + project files) bilan ishlaydi.

Oqim:
1. `app/bot/data/inbox.jsonl` dan o'qilmagan xabarlarni o'qish
2. cwd=D:\\TOTLI BI da claude CLI ni chaqirish (loyiha konteksti)
3. --resume <session_id> bilan dedicated Telegram suhbat thread saqlash
4. JSON javobdan response va session_id ajratib olish
5. notify-owner endpoint orqali Telegram'ga yuborish

Shu pattern claude_remote.py bilan bir xil — sinab ko'rilgan, ishonchli.
"""
from __future__ import annotations

import json
import os
import shutil
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
SESSION_FILE = INBOX_DIR / "responder_session.json"
LOCK = INBOX_DIR / "responder.lock"
LOG = ROOT / "watchdog.log"

NOTIFY_URL = os.environ.get(
    "CLAUDE_NOTIFY_URL",
    "http://10.243.165.156:8080/api/internal/notify-owner",
)
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "180"))
CLAUDE_MODEL = os.environ.get("CLAUDE_BOT_MODEL", "claude-opus-4-7[1m]")
LOCK_TIMEOUT_MIN = 15
MAX_BATCH = 10


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [responder] {msg}\n"
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def resolve_claude_path() -> str:
    """claude.cmd to'liq yo'lini topadi (claude_remote.py patterni)."""
    found = shutil.which("claude")
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            os.path.expandvars(r"%APPDATA%\npm\claude.bat"),
            os.path.expandvars(r"%LOCALAPPDATA%\npm\claude.cmd"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return "claude"


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


def get_session_id() -> str:
    if not SESSION_FILE.exists():
        return ""
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("session_id", "")
    except Exception:
        return ""


def save_session_id(sid: str) -> None:
    SESSION_FILE.write_text(json.dumps({"session_id": sid}), encoding="utf-8")


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
    parts = []
    for m in msgs[-MAX_BATCH:]:
        ts = m.get("ts", "")
        text = (m.get("text") or "").strip()
        if m.get("kind") == "photo":
            photo = m.get("photo", "")
            text = f"[FOTO yuborildi: {photo}] {text}".strip()
        parts.append(f"[{ts}] {text}")
    parts.append(
        "\nJavobni o'zbek tilida, qisqa va aniq ber. Loyihaning konteksti "
        "(CLAUDE.md, memory) avtomat yuklangan. Tool chaqiriqlarini imkon qadar "
        "minimum tut — agar zarur bo'lsa, qisqa raed/grep yetarli."
    )
    return "\n".join(parts)


def call_claude(prompt: str) -> tuple[str, str]:
    """Returns (response_text, new_session_id). Bo'sh string xato."""
    claude_bin = resolve_claude_path()
    sid = get_session_id()

    args = [claude_bin, "--print", "--output-format", "json", "--model", CLAUDE_MODEL]
    if sid:
        args += ["--resume", sid]
    args += ["--dangerously-skip-permissions", prompt]

    # Windows .cmd uchun cmd.exe /c ishlatish
    if sys.platform == "win32" and claude_bin.lower().endswith((".cmd", ".bat")):
        exec_args = ["cmd.exe", "/c"] + args
    else:
        exec_args = args

    try:
        result = subprocess.run(
            exec_args,
            cwd=str(ROOT),  # ← Loyiha root (CLAUDE.md + memory)
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log(f"claude timeout ({CLAUDE_TIMEOUT}s)")
        return "", sid
    except FileNotFoundError:
        log(f"claude CLI topilmadi: {claude_bin}")
        return "", sid
    except Exception as e:
        log(f"claude xato: {type(e).__name__}: {e}")
        return "", sid

    out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (result.stderr or b"").decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        log(f"claude exit={result.returncode} err={err[:200]}")
        # --resume failed — yangi session bilan urinish
        if sid and ("session" in err.lower() or "not found" in err.lower()):
            log("--resume muvaffaqiyatsiz, yangi session yaratamiz")
            args_new = [claude_bin, "--print", "--output-format", "json", "--model", CLAUDE_MODEL,
                        "--dangerously-skip-permissions", prompt]
            if sys.platform == "win32" and claude_bin.lower().endswith((".cmd", ".bat")):
                exec_args = ["cmd.exe", "/c"] + args_new
            else:
                exec_args = args_new
            try:
                result = subprocess.run(
                    exec_args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL, timeout=CLAUDE_TIMEOUT,
                )
                if result.returncode != 0:
                    return "", sid
                out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
            except Exception as e:
                log(f"fallback xato: {e}")
                return "", sid
        else:
            return "", sid

    try:
        data = json.loads(out)
        new_sid = data.get("session_id") or sid
        text = data.get("result") or data.get("content") or ""
        return text.strip(), new_sid
    except json.JSONDecodeError:
        log(f"JSON parse xato — output: {out[:200]}")
        return out.strip(), sid


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
        log(f"notify xato: {type(e).__name__}: {e}")
        return False


def main() -> int:
    msgs = read_unread()
    if not msgs:
        return 0

    if not acquire_lock():
        log(f"lock band ({len(msgs)} ta o'qilmagan kutmoqda)")
        return 0

    try:
        log(f"claude ga uzatilmoqda: {len(msgs)} ta xabar (cwd=ROOT)")
        prompt = build_prompt(msgs)
        response, new_sid = call_claude(prompt)

        if not response:
            log("claude bo'sh javob qaytardi — keyingi safar urinamiz")
            return 0

        if new_sid:
            save_session_id(new_sid)

        if not post_to_telegram(response):
            log("Telegramga yuborishda xato — last_seen yangilanmaydi")
            return 0

        latest_id = max(str(m.get("id", "")) for m in msgs)
        set_last_seen(latest_id)
        log(f"javob yuborildi ({len(response)} chars), last_seen={latest_id}, sid={new_sid[:8] if new_sid else 'no'}")
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
