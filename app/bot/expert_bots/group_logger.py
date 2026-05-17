"""Guruh xabarlarini JSONL faylga yozadi.

Barcha 11 expert bot bir processda ishlaydi — _seen_ids set shared bo'ladi.
Shuning uchun bir xabar faqat bir marta yoziladi (dedup).

Fayl: data/group_logs/YYYY-MM-DD_<chat_id>.jsonl
"""
from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram.types import Message

CWD = Path(os.environ.get("CLAUDE_BOT_CWD") or os.getcwd())
LOG_DIR = CWD / "data" / "group_logs"

# Shared dedup deque — cheksiz o'sishni oldini oladi (10k xabar ≈ ~1 MB RAM)
_seen_ids: deque = deque(maxlen=10_000)
_seen_set: set[str] = set()  # tez lookup uchun


def _log_path(chat_id: int) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return LOG_DIR / f"{today}_{chat_id}.jsonl"


def log_message(message: Message) -> None:
    """Guruh xabarini log faylga yozadi. Agar allaqachon yozilgan bo'lsa — o'tkazib yuboradi."""
    if not message.from_user:
        return

    key = f"{message.chat.id}_{message.message_id}"
    if key in _seen_set:
        return
    # deque to'lganda eng eski elementni avtomatik o'chiradi
    if len(_seen_ids) == _seen_ids.maxlen:
        old = _seen_ids[0]
        _seen_set.discard(old)
    _seen_ids.append(key)
    _seen_set.add(key)

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "msg_id": message.message_id,
        "chat_id": message.chat.id,
        "chat_title": message.chat.title or "",
        "user_id": message.from_user.id,
        "username": message.from_user.username or "",
        "full_name": message.from_user.full_name or "",
        "text": text,
        "reply_to": (
            message.reply_to_message.message_id
            if message.reply_to_message
            else None
        ),
    }

    try:
        with _log_path(message.chat.id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
