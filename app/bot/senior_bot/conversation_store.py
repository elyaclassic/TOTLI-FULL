"""Per-chat suhbat tarixini markdown'da saqlash.

`conversations/YYYY-MM-DD_{chat_id}.md` formatida. Foydalanuvchi ham bevosita
o'qiy oladi (transparent memory).

Har xabar:
```
## 14:23 — Elyor (uid=1340383182)
Savol matni shu yerda

### 14:23 — Senior (1843 tokens)
Javob shu yerda
```
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CONV_DIR = Path(os.environ.get("CLAUDE_BOT_CWD") or os.getcwd()) / "conversations"
CONV_DIR.mkdir(parents=True, exist_ok=True)

# Anthropic API'ga uzatish uchun oxirgi N ta xabar
HISTORY_LIMIT = int(os.environ.get("SENIOR_BOT_HISTORY", "10"))


def _path_for(chat_id: int, d: date | None = None) -> Path:
    d = d or date.today()
    return CONV_DIR / f"{d.isoformat()}_{chat_id}.md"


def append_user(chat_id: int, user_name: str, user_id: int, text: str) -> None:
    """Foydalanuvchi xabarini yozadi."""
    p = _path_for(chat_id)
    ts = datetime.now().strftime("%H:%M")
    block = f"\n## {ts} — {user_name} (uid={user_id})\n{text.strip()}\n"
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        logger.error(f"append_user fail: {e}")


def append_assistant(chat_id: int, text: str, meta: dict | None = None) -> None:
    """Bot javobini yozadi."""
    p = _path_for(chat_id)
    ts = datetime.now().strftime("%H:%M")
    tokens = ""
    if meta:
        tokens = f" ({meta.get('input_tokens', 0)}→{meta.get('output_tokens', 0)} tok, {meta.get('model', '')})"
    block = f"\n### {ts} — Senior{tokens}\n{text.strip()}\n"
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        logger.error(f"append_assistant fail: {e}")


def reset(chat_id: int) -> None:
    """Joriy kun faylini arxivlaydi (xabarlar yo'qolmaydi, lekin yangi suhbatda hisobga olinmaydi)."""
    p = _path_for(chat_id)
    if p.exists():
        archive = p.with_suffix(f".reset-{int(time.time())}.md")
        try:
            p.rename(archive)
        except OSError as e:
            logger.error(f"reset rename fail: {e}")


_USER_RE = re.compile(r"^## (\d{2}:\d{2}) — (.+?) \(uid=\d+\)\s*$")
_ASSIST_RE = re.compile(r"^### (\d{2}:\d{2}) — Senior(\s*\(.*?\))?\s*$")


def load_recent(chat_id: int, limit: int | None = None) -> list[dict]:
    """Bugungi suhbat tarixini Anthropic format'iga keltiradi.

    Returns:
        [{"role": "user"|"assistant", "content": "..."}, ...] oxirgi `limit` xabar
    """
    limit = limit or HISTORY_LIMIT
    p = _path_for(chat_id)
    if not p.exists():
        return []
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return []

    messages = []
    current_role = None
    current_buf: list[str] = []

    def flush():
        if current_role and current_buf:
            body = "\n".join(current_buf).strip()
            if body:
                messages.append({"role": current_role, "content": body})

    for line in content.splitlines():
        if _USER_RE.match(line):
            flush()
            current_role = "user"
            current_buf = []
        elif _ASSIST_RE.match(line):
            flush()
            current_role = "assistant"
            current_buf = []
        else:
            if current_role:
                current_buf.append(line)
    flush()

    # Anthropic conversation user/assistant tartibida ketma-ket bo'lishi kerak
    # (qator dublikatlarsiz). Limit oxiridan.
    return messages[-limit:]
