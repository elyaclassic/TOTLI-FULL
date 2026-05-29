import asyncio
import logging
import threading

from app.bot.customer_bot.queries import fmt_money

logger = logging.getLogger(__name__)


def msg_order_confirmed(order):
    return (
        f"✅ Buyurtmangiz qabul qilindi\n"
        f"№ {order.number}\n"
        f"Summa: <b>{fmt_money(order.total)}</b> so'm"
    )


def msg_order_dispatched(order):
    return (
        f"🚚 Buyurtmangiz yo'lda\n"
        f"№ {order.number}\n"
        f"Tez orada yetkaziladi."
    )


def msg_order_delivered(order, balance):
    return (
        f"📦 Buyurtma yetkazildi\n"
        f"№ {order.number}\n"
        f"To'langan: <b>{fmt_money(order.paid)}</b> so'm\n"
        f"Joriy qoldiq: <b>{fmt_money(balance)}</b> so'm"
    )


def msg_agent_payment(agent_code, agent_name, amount, balance):
    return (
        f"💰 To'lov qabul qilindi\n"
        f"Agent {agent_code} {agent_name} <b>{fmt_money(amount)}</b> so'm to'lov qabul qildi.\n"
        f"Joriy qoldiq: <b>{fmt_money(balance)}</b> so'm"
    )


def _send_via_token(chat_ids, text):
    """Yangi Bot instance ochib yuboradi, sessiyani yopadi. Sync kontekst."""
    from app.bot.customer_bot.config import BOT_TOKEN
    if not BOT_TOKEN or not chat_ids:
        return

    async def _run():
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        try:
            for cid in chat_ids:
                try:
                    await bot.send_message(int(cid), text)
                except Exception as e:
                    logger.warning(f"customer_bot send fail {cid}: {e}")
        finally:
            await bot.session.close()

    def _run_in_thread():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"customer_bot thread error: {e}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        threading.Thread(target=_run_in_thread, daemon=True).start()
    else:
        _run_in_thread()


def notify_customer(partner_id, text):
    """Partner'ning approved Telegram linklariga xabar. Fire-and-forget, hech qachon raise qilmaydi."""
    try:
        from app.models.database import SessionLocal
        from app.bot.customer_bot.registration import approved_telegram_ids_for_partner
        db = SessionLocal()
        try:
            chat_ids = approved_telegram_ids_for_partner(db, partner_id)
        finally:
            db.close()
        _send_via_token(chat_ids, text)
    except Exception as e:
        logger.warning(f"notify_customer error: {e}")
