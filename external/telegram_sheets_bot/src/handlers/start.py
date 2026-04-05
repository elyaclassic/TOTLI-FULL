"""Minimal handlerlar — keyin kengaytirasiz."""
from aiogram import Router
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message

from src.access import AllowedUserFilter, deny_message
from src.keyboards import main_menu_kb

router = Router()
router.message.filter(AllowedUserFilter())


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Salom!\n\n"
        "Tugmalar orqali mijoz tanlang, kirim/chiqim kiriting yoki hisobot oling.\n\n"
        "Matn va ovoz ham fallback sifatida ishlaydi.",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.message(F.text.startswith("/"))
async def deny_unknown_allowed_commands(message: Message) -> None:
    await message.answer("Buyruq tushunilmadi.", reply_markup=main_menu_kb())


deny_router = Router()


@deny_router.message()
async def deny_all_messages(message: Message) -> None:
    await deny_message(message)
