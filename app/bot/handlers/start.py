"""Start va menyu handlerlari"""
import asyncio
from datetime import date

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from app.bot.config import ALLOWED_CHAT_IDS
from app.bot.keyboards.main_menu import main_menu_kb, main_menu_reply_kb, MENU_TEXT_MAP, period_kb
from app.bot.services.report_queries import report_debtors
from app.models.database import SessionLocal

router = Router()


def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_CHAT_IDS


@router.message(Command("start", "menu", "help"))
async def cmd_start(message: Message):
    if not is_allowed(message.from_user.id):
        await message.answer(
            f"⛔ Sizga ruxsat berilmagan.\n\n"
            f"Sizning ID: <code>{message.from_user.id}</code>\n"
            f"Admin ga shu ID ni yuboring.",
            parse_mode="HTML",
        )
        return
    await message.answer(
        f"Salom, <b>{message.from_user.full_name}</b>!\n"
        f"TOTLI HOLVA hisobot boti tayyor.\n"
        f"Quyidagi menyudan tanlang:",
        parse_mode="HTML",
        reply_markup=main_menu_reply_kb(),
    )


@router.message(F.text.in_(MENU_TEXT_MAP.keys()))
async def on_menu_button(message: Message):
    """Pastdagi menyu tugmalari bosilganda"""
    if not is_allowed(message.from_user.id):
        return
    report_type = MENU_TEXT_MAP[message.text]
    # Qarzdorlar uchun davr kerak emas
    if report_type == "debtors":
        db = SessionLocal()
        try:
            text = await asyncio.to_thread(report_debtors, db, date.today(), date.today())
        finally:
            db.close()
        await message.answer(text, parse_mode="HTML")
        return
    title = message.text
    await message.answer(
        f"{title}\n\nDavrni tanlang:",
        parse_mode="HTML",
        reply_markup=period_kb(report_type),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await callback.message.delete()
    await callback.message.answer(
        "Menyudan tanlang:",
        parse_mode="HTML",
        reply_markup=main_menu_reply_kb(),
    )
    await callback.answer()
