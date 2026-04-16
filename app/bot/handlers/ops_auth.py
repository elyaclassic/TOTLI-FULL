"""PIN authentifikatsiya — bot ichidan ma'lumot kirityish uchun.

Foydalanuvchi "Amaliyot" tugmasini bossa — PIN so'raladi.
Muvaffaqiyatli PIN → BOT_PIN_SESSION_HOURS davomida eslab qolinadi (in-memory).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Dict

from app.bot.config import OPS_CHAT_IDS, BOT_ADMIN_PIN, BOT_PIN_SESSION_HOURS

_session_lock = threading.Lock()
_pin_sessions: Dict[int, datetime] = {}  # chat_id -> expires_at


def is_ops_allowed(user_id: int) -> bool:
    """Foydalanuvchi umuman ops ishlata oladimi (whitelist)."""
    return user_id in OPS_CHAT_IDS


def pin_ok(user_id: int) -> bool:
    """PIN sessiyasi faolmi tekshirish."""
    with _session_lock:
        exp = _pin_sessions.get(user_id)
        if not exp:
            return False
        if datetime.now() >= exp:
            _pin_sessions.pop(user_id, None)
            return False
        return True


def pin_grant(user_id: int) -> datetime:
    """PIN sessiyasini boshlash — hozirdan BOT_PIN_SESSION_HOURS soat faol."""
    with _session_lock:
        exp = datetime.now() + timedelta(hours=max(1, BOT_PIN_SESSION_HOURS))
        _pin_sessions[user_id] = exp
        return exp


def pin_revoke(user_id: int) -> None:
    """PIN sessiyasini bekor qilish (foydalanuvchi /logout bossa)."""
    with _session_lock:
        _pin_sessions.pop(user_id, None)


def check_pin(entered: str) -> bool:
    """PIN kod to'g'riligini tekshirish."""
    if not entered or not BOT_ADMIN_PIN:
        return False
    return entered.strip() == BOT_ADMIN_PIN.strip()
