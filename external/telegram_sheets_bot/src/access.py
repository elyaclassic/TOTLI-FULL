"""Botga kirish nazorati."""
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.config import ADMIN_TELEGRAM_IDS, ALLOWED_TELEGRAM_IDS, RAHBAR_TELEGRAM_IDS, XODIM_TELEGRAM_IDS


def is_allowed_user_id(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if not ALLOWED_TELEGRAM_IDS:
        return True
    return user_id in ALLOWED_TELEGRAM_IDS


def get_user_role(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    if user_id in ADMIN_TELEGRAM_IDS:
        return "admin"
    if user_id in RAHBAR_TELEGRAM_IDS:
        return "rahbar"
    if user_id in XODIM_TELEGRAM_IDS:
        return "xodim"
    # Role ro'yxatlari to'liq kiritilmaguncha, allowlist dagi eski foydalanuvchilar blok bo'lib qolmasin.
    if is_allowed_user_id(user_id):
        return "admin"
    return None


def has_role(user_id: int | None, *roles: str) -> bool:
    role = get_user_role(user_id)
    return role in roles


class AllowedUserFilter(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return is_allowed_user_id(getattr(user, "id", None))


class RoleFilter(BaseFilter):
    def __init__(self, *roles: str):
        self.roles = roles

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return has_role(getattr(user, "id", None), *self.roles)


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


async def deny_role_message(message: Message) -> None:
    await message.answer("⛔ Sizda bu bo'limga ruxsat yo'q.")


async def deny_role_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer("⛔ Sizda bu bo'limga ruxsat yo'q.")
    await callback.answer("Ruxsat yo'q", show_alert=True)
