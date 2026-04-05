"""Botga kirish nazorati."""
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.config import ALLOWED_TELEGRAM_IDS


def is_allowed_user_id(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if not ALLOWED_TELEGRAM_IDS:
        return True
    return user_id in ALLOWED_TELEGRAM_IDS


class AllowedUserFilter(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return is_allowed_user_id(getattr(user, "id", None))


async def deny_message(message: Message) -> None:
    uid = message.from_user.id if message.from_user else "?"
    await message.answer(
        "⛔ Sizga ruxsat berilmagan.\n\n"
        f"Sizning Telegram ID: <code>{uid}</code>",
        parse_mode="HTML",
    )


async def deny_callback(callback: CallbackQuery) -> None:
    uid = callback.from_user.id if callback.from_user else "?"
    if callback.message:
        await callback.message.answer(
            "⛔ Sizga ruxsat berilmagan.\n\n"
            f"Sizning Telegram ID: <code>{uid}</code>",
            parse_mode="HTML",
        )
    await callback.answer("Ruxsat yo'q", show_alert=True)
