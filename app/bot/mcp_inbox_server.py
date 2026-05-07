"""MCP server — Telegram inbox xabarlarini Claude Code ga ekspoz qiladi.

Ishga tushirish (Claude Code .mcp.json orqali avtomatik):
    python app/bot/mcp_inbox_server.py

Tools:
- list_inbox(limit, only_unread)  — xabarlar ro'yxati
- get_message(msg_id)             — bitta xabar (rasm yo'li bilan)
- mark_read(msg_id)                — shu ID gacha o'qildi belgisi
- mark_all_read()                  — barcha xabarlarni o'qildi belgisi
- inbox_summary()                  — qisqa statistika (jami/o'qilmagan)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from app.bot import inbox as _inbox

mcp = FastMCP("totli-telegram-inbox")


def _format_message(rec: dict) -> str:
    lines = [
        f"ID: {rec.get('id', '')}",
        f"Vaqt: {rec.get('ts', '')}",
        f"Kim: uid={rec.get('uid', '')}",
        f"Tur: {rec.get('kind', 'text')}",
    ]
    text = rec.get("text", "")
    if text:
        lines.append(f"\nMatn:\n{text}")
    photo = rec.get("photo", "")
    if photo:
        lines.append(f"\nRasm: {photo}")
    return "\n".join(lines)


@mcp.tool()
def list_inbox(limit: int = 20, only_unread: bool = True) -> str:
    """Telegram bot orqali kelgan xabarlar ro'yxati (yangidan eskigacha).

    Args:
        limit: Maksimal qaytariladigan xabar soni (default 20).
        only_unread: True bo'lsa faqat o'qilmaganlar (default True).
    """
    msgs = _inbox.list_messages(limit=limit, only_unread=only_unread)
    if not msgs:
        return "Inbox bo'sh — yangi xabarlar yo'q." if only_unread else "Inbox bo'sh."

    out = [f"Jami: {len(msgs)} ta xabar"]
    for rec in msgs:
        kind_icon = "📷" if rec.get("kind") == "photo" else "💬"
        text_preview = (rec.get("text") or "").strip().replace("\n", " ")
        if len(text_preview) > 80:
            text_preview = text_preview[:80] + "…"
        out.append(
            f"\n{kind_icon} [{rec.get('id', '')}] {rec.get('ts', '')}\n   {text_preview}"
        )
    return "\n".join(out)


@mcp.tool()
def get_message(msg_id: str) -> str:
    """Bitta xabarning to'liq matni va rasm yo'li (agar bor bo'lsa).

    Args:
        msg_id: list_inbox dan olingan xabar ID si.
    """
    rec = _inbox.get_message(msg_id)
    if not rec:
        return f"Xabar topilmadi: {msg_id}"
    return _format_message(rec)


@mcp.tool()
def mark_read(msg_id: str) -> str:
    """Berilgan ID gacha bo'lgan barcha xabarlarni o'qildi deb belgilash.

    Args:
        msg_id: O'qildi deb belgilanadigan oxirgi xabar ID si.
    """
    if _inbox.mark_read(msg_id):
        return f"Belgilandi: {msg_id} va undan oldingi barcha xabarlar o'qildi."
    return f"Xabar topilmadi: {msg_id}"


@mcp.tool()
def mark_all_read() -> str:
    """Barcha xabarlarni o'qildi deb belgilash."""
    n = _inbox.mark_all_read()
    return f"O'qildi belgilandi: {n} ta xabar."


@mcp.tool()
def inbox_summary() -> str:
    """Inbox holati: jami va o'qilmagan xabarlar soni."""
    total = _inbox.list_messages(limit=10000, only_unread=False)
    unread = _inbox.list_messages(limit=10000, only_unread=True)
    if not total:
        return "Inbox bo'sh."
    last = total[0]
    return (
        f"Jami: {len(total)} ta xabar\n"
        f"O'qilmagan: {len(unread)} ta\n"
        f"Oxirgi: [{last.get('id')}] {last.get('ts')} ({last.get('kind')})"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
