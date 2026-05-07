"""Inbox writer/reader — Telegram bot xabarlari uchun fayl-orqali queue.

Bot kelgan xabarlarni shu modul orqali yozadi (`append_message`).
MCP server (`mcp_inbox_server.py`) shu modul orqali o'qiydi.

Format:
- JSONL (`inbox.jsonl`) — har qator: {ts, id, uid, kind, text, photo, read}
- Markdown (`inbox.md`) — odam o'qishi uchun, append-only

ID — UNIX timestamp + counter, monotonik o'sadi.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INBOX_JSONL = DATA_DIR / "inbox.jsonl"
INBOX_MD = DATA_DIR / "inbox.md"
READ_MARKER = DATA_DIR / "inbox.read_id"


def _next_id() -> str:
    return f"{int(time.time() * 1000)}"


def append_message(uid: int, kind: str, text: str, photo_path: Optional[str] = None) -> str:
    """Inboxga yangi xabar qo'sh. ID ni qaytaradi.

    kind: "text" | "photo"
    """
    msg_id = _next_id()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "ts": ts,
        "id": msg_id,
        "uid": uid,
        "kind": kind,
        "text": text or "",
        "photo": photo_path or "",
    }

    with INBOX_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    md_lines = [
        f"\n## [{ts}] uid={uid} id={msg_id} ({kind})",
    ]
    if text:
        md_lines.append(f"\n{text}")
    if photo_path:
        rel = photo_path.replace("\\", "/")
        md_lines.append(f"\n📷 `{rel}`")
    md_lines.append("\n---")

    with INBOX_MD.open("a", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return msg_id


def _get_last_read_id() -> str:
    try:
        return READ_MARKER.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""


def _set_last_read_id(msg_id: str) -> None:
    READ_MARKER.write_text(msg_id, encoding="utf-8")


def list_messages(limit: int = 20, only_unread: bool = False) -> list[dict[str, Any]]:
    """Oxirgi N xabarni qaytaradi (yangidan eskigacha)."""
    if not INBOX_JSONL.exists():
        return []

    last_read = _get_last_read_id() if only_unread else ""
    out: list[dict[str, Any]] = []

    with INBOX_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if only_unread and last_read and rec.get("id", "") <= last_read:
                continue
            out.append(rec)

    out.sort(key=lambda r: r.get("id", ""), reverse=True)
    return out[:limit]


def get_message(msg_id: str) -> Optional[dict[str, Any]]:
    if not INBOX_JSONL.exists():
        return None
    with INBOX_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if rec.get("id") == msg_id:
                return rec
    return None


def mark_read(msg_id: str) -> bool:
    """Xabarni o'qildi deb belgilash. ID dan oldingi/teng barcha xabarlar o'qilgan hisoblanadi."""
    if not get_message(msg_id):
        return False
    _set_last_read_id(msg_id)
    return True


def mark_all_read() -> int:
    """Barcha xabarlarni o'qildi deb belgilash. O'qilgan miqdorni qaytaradi."""
    msgs = list_messages(limit=10000, only_unread=True)
    if msgs:
        _set_last_read_id(msgs[0]["id"])
    return len(msgs)
