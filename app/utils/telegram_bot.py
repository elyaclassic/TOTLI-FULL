"""
Telegram bot integratsiya — chat tizimi bilan bog'lanish.

Telegram foydalanuvchilari guruh yoki direct chatga qo'shilishi mumkin.
Bot xabarlarni ikki tomonga relay qiladi: Telegram <-> Web chat.

BOT_TOKEN ni .env yoki config dan olish kerak.
"""

import os
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Optional

logger = logging.getLogger("telegram_bot")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Polling loop reference (to stop it)
_polling_task: Optional[asyncio.Task] = None
_last_update_id = 0


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """Telegram ga xabar yuborish"""
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN sozlanmagan")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{API_BASE}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            if resp.status_code == 200:
                return True
            logger.error(f"Telegram send error: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram send exception: {e}")
        return False


async def get_bot_info() -> dict:
    """Bot ma'lumotlarini olish (getMe)"""
    if not BOT_TOKEN:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{API_BASE}/getMe")
            if resp.status_code == 200:
                return resp.json().get("result", {})
    except Exception as e:
        logger.error(f"getMe error: {e}")
    return {}


async def _process_update(update: dict):
    """Bitta Telegram update ni qayta ishlash"""
    from app.models.database import SessionLocal, ChatTelegramLink, ChatMessage, ChatParticipant, ChatThread
    from app.routes.chat import hub, _bump_unread_for_others

    msg = update.get("message")
    if not msg:
        return

    chat = msg.get("chat", {})
    tg_chat_id = str(chat.get("id", ""))
    from_user = msg.get("from", {})
    tg_user_id = str(from_user.get("id", ""))
    tg_username = from_user.get("username", "")
    tg_full_name = (from_user.get("first_name", "") + " " + from_user.get("last_name", "")).strip()
    text = msg.get("text", "")

    if not text or not tg_user_id:
        return

    # /start command — foydalanuvchiga ma'lumot berish
    if text.startswith("/start"):
        await send_telegram_message(tg_chat_id,
            "Salom! Men TOTLI HOLVA chat botiman.\n\n"
            "Admin sizni chatga qo'shishi kerak. "
            f"Sizning Telegram ID: <b>{tg_user_id}</b>\n"
            "Bu ID ni admin ga bering."
        )
        return

    # Bu telegram_chat_id ga bog'langan threadlarni topish
    db = SessionLocal()
    try:
        links = db.query(ChatTelegramLink).filter(
            ChatTelegramLink.telegram_chat_id == tg_user_id,
            ChatTelegramLink.is_active == True,
        ).all()

        if not links:
            await send_telegram_message(tg_chat_id,
                "Siz hali hech qaysi chatga qo'shilmagansiz.\n"
                f"Telegram ID: <b>{tg_user_id}</b>\n"
                "Admin sizni chatga qo'shishi kerak."
            )
            return

        # Har bir bog'langan threadga xabar yuborish
        for link in links:
            # Link ma'lumotlarini yangilash
            if tg_username and link.telegram_username != tg_username:
                link.telegram_username = tg_username
            if tg_full_name and link.telegram_full_name != tg_full_name:
                link.telegram_full_name = tg_full_name
            db.commit()

            # Xabarni DB ga saqlash (sender_id=None — Telegram user)
            chat_msg = ChatMessage(
                thread_id=link.thread_id,
                sender_id=None,
                body=text,
                telegram_sender_name=tg_full_name or tg_username or f"TG:{tg_user_id}",
                created_at=datetime.now(),
            )
            db.add(chat_msg)
            db.commit()
            db.refresh(chat_msg)

            # Unread count oshirish (barcha participantlar uchun)
            parts = db.query(ChatParticipant).filter(ChatParticipant.thread_id == link.thread_id).all()
            for p in parts:
                p.unread_count = int(p.unread_count or 0) + 1
            db.commit()

            # WebSocket orqali broadcast
            try:
                await hub.broadcast(link.thread_id, {
                    "type": "message",
                    "thread_id": link.thread_id,
                    "message": {
                        "id": chat_msg.id,
                        "sender_id": None,
                        "sender_name": f"📱 {chat_msg.telegram_sender_name}",
                        "body": chat_msg.body,
                        "created_at": chat_msg.created_at.isoformat(),
                        "is_telegram": True,
                    },
                })
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
    finally:
        db.close()


async def relay_to_telegram(thread_id: int, sender_name: str, body: str):
    """Web chatdan Telegram ga xabar yuborish"""
    from app.models.database import SessionLocal, ChatTelegramLink

    if not BOT_TOKEN:
        return

    db = SessionLocal()
    try:
        links = db.query(ChatTelegramLink).filter(
            ChatTelegramLink.thread_id == thread_id,
            ChatTelegramLink.is_active == True,
        ).all()

        for link in links:
            text = f"<b>{sender_name}</b>:\n{body}"
            await send_telegram_message(link.telegram_chat_id, text)
    finally:
        db.close()


async def poll_updates():
    """Telegram dan yangilanishlarni polling qilish"""
    global _last_update_id

    if not BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN yo'q — polling ishlamaydi")
        return

    logger.info("Telegram bot polling boshlandi...")
    while True:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.get(f"{API_BASE}/getUpdates", params={
                    "offset": _last_update_id + 1,
                    "timeout": 30,
                    "allowed_updates": '["message"]',
                })
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        _last_update_id = update.get("update_id", _last_update_id)
                        try:
                            await _process_update(update)
                        except Exception as e:
                            logger.error(f"Update processing error: {e}")
                else:
                    logger.error(f"Polling error: {resp.status_code}")
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("Telegram polling to'xtatildi")
            break
        except Exception as e:
            logger.error(f"Polling exception: {e}")
            await asyncio.sleep(5)


def start_telegram_bot():
    """Telegram botni background task sifatida ishga tushirish"""
    global _polling_task
    if not BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN sozlanmagan — bot ishga tushmaydi")
        return
    loop = asyncio.get_event_loop()
    _polling_task = loop.create_task(poll_updates())
    logger.info("Telegram bot ishga tushdi")


def stop_telegram_bot():
    """Telegram botni to'xtatish"""
    global _polling_task
    if _polling_task:
        _polling_task.cancel()
        _polling_task = None
