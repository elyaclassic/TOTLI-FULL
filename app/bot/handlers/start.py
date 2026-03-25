"""Start va menyu handlerlari"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from app.bot.keyboards.main_menu import main_menu_kb

router = Router()


@router.message(Command("start", "menu", "help"))
async def cmd_start(message: Message):
    await message.answer(
        f"Salom, <b>{message.from_user.full_name}</b>!\n\n"
        f"TOTLI HOLVA hisobot botiga xush kelibsiz.\n"
        f"Quyidagi bo'limlardan birini tanlang:\n\n"
        f"Sizning Telegram ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Quyidagi bo'limlardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()
