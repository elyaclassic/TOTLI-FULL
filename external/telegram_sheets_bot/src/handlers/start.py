"""Minimal handlerlar — keyin kengaytirasiz."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.keyboards import main_menu_kb

router = Router()


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Salom!\n\n"
        "Tugmalar orqali mijoz tanlang, kirim/chiqim kiriting yoki hisobot oling.\n\n"
        "Matn va ovoz ham fallback sifatida ishlaydi.",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
