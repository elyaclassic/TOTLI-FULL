"""Barcha hisobotlar uchun yagona handler — report va period callback lar"""
import asyncio
from datetime import datetime, date
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.bot.config import ALLOWED_CHAT_IDS
from app.bot.keyboards.main_menu import period_kb, back_menu_kb
from app.bot.services.report_queries import (
    parse_period,
    report_attendance, report_sales, report_cashflow, report_expenses,
    report_debtors, report_salaries, report_kpi, report_top_products,
    report_agents, report_returns, report_production,
)
from app.models.database import SessionLocal

router = Router()

REPORT_TITLES = {
    "attendance": "📋 Davomat",
    "sales": "💰 Savdo",
    "cashflow": "💵 Pul oqimi",
    "expenses": "📉 Harajatlar",
    "debtors": "📌 Qarzdorlar",
    "salaries": "💳 Ish haqi",
    "kpi": "📊 KPI",
    "top_products": "🏆 Top mahsulotlar",
    "agents": "🚗 Agentlar",
    "production": "🏭 Ishlab chiqarish",
    "returns": "🔄 Obmen/Vozvrat",
}

REPORT_FUNCS = {
    "attendance": report_attendance,
    "sales": report_sales,
    "cashflow": report_cashflow,
    "expenses": report_expenses,
    "debtors": report_debtors,
    "salaries": report_salaries,
    "kpi": report_kpi,
    "top_products": report_top_products,
    "agents": report_agents,
    "production": report_production,
    "returns": report_returns,
}


class CustomPeriod(StatesGroup):
    waiting_dates = State()


@router.callback_query(F.data.startswith("report:"))
async def cb_report_select(callback: CallbackQuery):
    """Hisobot turi tanlanganda — davr tanlash ekrani"""
    if callback.from_user.id not in ALLOWED_CHAT_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    report_type = callback.data.split(":")[1]
    title = REPORT_TITLES.get(report_type, report_type)
    # Qarzdorlar uchun davr tanlash kerak emas
    if report_type == "debtors":
        await callback.answer("Yuklanmoqda...")
        db = SessionLocal()
        try:
            text = await asyncio.to_thread(report_debtors, db, date.today(), date.today())
        finally:
            db.close()
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_menu_kb())
        return
    await callback.message.edit_text(
        f"{title}\n\nDavrni tanlang:",
        parse_mode="HTML",
        reply_markup=period_kb(report_type),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("period:"))
async def cb_period_select(callback: CallbackQuery):
    """Davr tanlanganda — hisobotni generatsiya qilish"""
    parts = callback.data.split(":")
    report_type = parts[1]
    period = parts[2]
    func = REPORT_FUNCS.get(report_type)
    if not func:
        await callback.answer("Noma'lum hisobot turi")
        return
    await callback.answer("Yuklanmoqda...")
    start, end = parse_period(period)
    db = SessionLocal()
    try:
        text = await asyncio.to_thread(func, db, start, end)
    except Exception as e:
        text = f"Xatolik: {str(e)[:200]}"
    finally:
        db.close()
    # Telegram 4096 belgi chegarasi
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (qisqartirildi)"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_menu_kb())


@router.callback_query(F.data.startswith("custom:"))
async def cb_custom_period(callback: CallbackQuery, state: FSMContext):
    """Davr tanlash — foydalanuvchi sanalarni yozadi"""
    report_type = callback.data.split(":")[1]
    title = REPORT_TITLES.get(report_type, report_type)
    await state.set_state(CustomPeriod.waiting_dates)
    await state.update_data(report_type=report_type)
    await callback.message.edit_text(
        f"{title}\n\n"
        f"Sanalarni yozing (boshlanish va tugash):\n\n"
        f"Misol: <code>01.03.2026-25.03.2026</code>\n"
        f"yoki: <code>01.03.2026 25.03.2026</code>",
        parse_mode="HTML",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.message(CustomPeriod.waiting_dates)
async def on_custom_dates(message: Message, state: FSMContext):
    """Foydalanuvchi sanalarni yozganda"""
    data = await state.get_data()
    report_type = data.get("report_type", "sales")
    await state.clear()

    text_input = message.text.strip()
    # Formatlarni sinash: "01.03.2026-25.03.2026", "01.03.2026 25.03.2026", "2026-03-01 2026-03-25"
    separators = ["-", " ", "—", "/"]
    start_date = end_date = None

    for sep in separators:
        parts = [p.strip() for p in text_input.split(sep) if p.strip()]
        if len(parts) >= 2:
            # Oxirgi 2 ta qismni olish (sana1-sana2)
            # "01.03.2026-25.03.2026" -> ["01.03.2026", "25.03.2026"]
            date_parts = parts[-2:]
            # Agar birinchi qism kunda bo'lsa
            if len(date_parts[0]) >= 8:
                start_date = _try_parse_date(date_parts[0])
                end_date = _try_parse_date(date_parts[1])
                if start_date and end_date:
                    break

    if not start_date or not end_date:
        await message.answer(
            "❌ Sanani tushunolmadim.\n\n"
            "Qayta yozing: <code>01.03.2026-25.03.2026</code>",
            parse_mode="HTML",
            reply_markup=back_menu_kb(),
        )
        return

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    func = REPORT_FUNCS.get(report_type)
    if not func:
        await message.answer("Noma'lum hisobot turi", reply_markup=back_menu_kb())
        return

    db = SessionLocal()
    try:
        result = await asyncio.to_thread(func, db, start_date, end_date)
    except Exception as e:
        result = f"Xatolik: {str(e)[:200]}"
    finally:
        db.close()

    if len(result) > 4000:
        result = result[:4000] + "\n\n... (qisqartirildi)"
    await message.answer(result, parse_mode="HTML", reply_markup=back_menu_kb())


def _try_parse_date(s: str):
    """Sanani parse qilish: 01.03.2026, 2026-03-01, 01/03/2026"""
    s = s.strip().rstrip("-").rstrip("/")
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
