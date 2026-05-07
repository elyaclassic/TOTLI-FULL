"""Claude Code <-> Telegram bot sinxronlash hook.

Bu skript Claude Code hooklari tomonidan chaqiriladi:

1. Stop event (Claude turn yakuni):
     python claude_telegram_sync.py --stop
   Stdin'dan JSON keladi: {"transcript_path": "...", "session_id": "...", ...}
   Transcript'dan oxirgi assistant javobini o'qib, /api/internal/notify-owner ga POST qiladi.

2. UserPromptSubmit event (foydalanuvchi prompt yuborganda):
     python claude_telegram_sync.py --prompt
   Stdin'dan JSON keladi: {"prompt": "...", ...}
   Inbox dan yangi xabarlar bo'lsa, ular ham promptga qo'shilishi uchun stdout'ga chiqaradi
   (Claude o'qib biladi).

Server URL env: CLAUDE_NOTIFY_URL (default http://10.243.165.156:8080/api/internal/notify-owner)
                — uvicorn faqat shu IP ga bind qilingan (start.bat BIND_HOST), shuning uchun 127.0.0.1 ishlamaydi
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

NOTIFY_URL = os.environ.get("CLAUDE_NOTIFY_URL", "http://10.243.165.156:8080/api/internal/notify-owner")
INBOX_DIR = Path(__file__).resolve().parent.parent / "app" / "bot" / "data"
INBOX_FILE = INBOX_DIR / "inbox.jsonl"
INBOX_LAST_SEEN = INBOX_DIR / "claude_last_seen.txt"
SYNC_LOG = Path(__file__).resolve().parent.parent / "claude_telegram_sync.log"


def _log(msg: str) -> None:
    """Debug uchun har chaqiriqni log qiladi."""
    import time
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    try:
        with SYNC_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _http_post_json(url: str, payload: dict, timeout: int = 5) -> tuple:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
    except Exception as e:
        return 0, str(e)


def _read_input_json() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _extract_last_assistant_text(transcript_path: str) -> str:
    """JSONL transcript dan oxirgi assistant text'ni topib qaytaradi."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    last_text = ""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                msg = obj.get("message") or obj
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    last_text = content
                elif isinstance(content, list):
                    parts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            parts.append(c.get("text") or "")
                    if parts:
                        last_text = "\n".join(parts).strip()
    except Exception:
        pass
    return last_text


def cmd_stop():
    """Stop event - Claude javobini Telegramga push qilish."""
    payload = _read_input_json()
    transcript = payload.get("transcript_path") or ""
    _log(f"[stop] transcript={transcript or '(YOQ)'}")
    text = _extract_last_assistant_text(transcript).strip()
    if not text:
        _log("[stop] javob bosh — yuborilmadi")
        return 0
    if len(text) > 3500:
        text = text[:3500] + "...\n[uzun javob qisqartirildi]"
    _log(f"[stop] notify URL={NOTIFY_URL} len={len(text)}")
    code, body = _http_post_json(NOTIFY_URL, {"text": text})
    if code == 200:
        _log("[stop] yuborildi OK")
        return 0
    _log(f"[stop] FAIL code={code} body={body[:300]}")
    sys.stderr.write(f"[claude_telegram_sync] notify failed: {code} {body[:200]}\n")
    return 0  # hook xatosi Claude'ni to'xtatmasin


def cmd_prompt():
    """UserPromptSubmit event - inbox da yangi Telegram xabarlar bo'lsa, contextga qo'sh."""
    if not INBOX_FILE.exists():
        return 0
    messages = []
    try:
        with open(INBOX_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return 0
    if not messages:
        return 0
    last_seen = ""
    if INBOX_LAST_SEEN.exists():
        try:
            last_seen = INBOX_LAST_SEEN.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    new_msgs = [m for m in messages if str(m.get("id", "")) > last_seen]
    if not new_msgs:
        return 0
    new_msgs.sort(key=lambda m: str(m.get("id", "")))
    parts = []
    for m in new_msgs[-10:]:
        ts = m.get("ts", "")
        kind = m.get("kind", "text")
        text = m.get("text", "") or ""
        if kind == "photo":
            text = f"[FOTO] {text}".strip()
        parts.append(f"[Telegram {ts}] {text}")
    if parts:
        sys.stdout.write("\n--- Yordamchim bot orqali yangi xabar(lar) ---\n")
        sys.stdout.write("\n".join(parts))
        sys.stdout.write("\n--- ---\n")
    try:
        latest_id = str(max(str(m.get("id", "")) for m in new_msgs))
        INBOX_LAST_SEEN.write_text(latest_id, encoding="utf-8")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--stop", action="store_true")
    g.add_argument("--prompt", action="store_true")
    args = p.parse_args()
    if args.stop:
        sys.exit(cmd_stop())
    elif args.prompt:
        sys.exit(cmd_prompt())
