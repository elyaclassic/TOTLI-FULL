"""Telegram OCR — rasm yuboriladi, o'qiladi, foydalanuvchi tasdiqlaydi.

Oqim: foto keladi → ocr_service (Claude Vision) → natija matn + inline tugmalar
(✅ Tasdiqlash / ❌ Bekor). Faqat ops-ruxsatli foydalanuvchi.

YAGNI: bu reja OCR natijani KO'RSATISH va tasdiqlashni qamraydi. Tasdiqlangan
natijani to'g'ridan-to'g'ri xaridga yozish — keyingi bosqich (avval OCR aniqligini
real hujjatlarda sinash kerak).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.bot.handlers.ops_auth import is_ops_allowed
from app.services.ocr_service import extract_from_image, OcrCliError, OcrParseError

logger = logging.getLogger(__name__)
router = Router()


def _format_result(d: dict) -> str:
    lines = [f"<b>📄 Hujjat:</b> {d.get('hujjat_turi')}  •  ishonch: {d.get('ishonch')}"]
    if d.get("sana"):
        lines.append(f"📅 Sana: {d['sana']}")
    if d.get("taminotchi"):
        lines.append(f"🏷 Ta'minotchi: {d['taminotchi']}")
    lines.append(f"💱 Valyuta: {d.get('valyuta')}  •  To'lov: {d.get('tolov_turi')}")
    lines.append("")
    for q in d.get("qatorlar", []):
        lines.append(f"• {q['nomi']} — {q['miqdor']:g} {q['birlik']} × {q['narx']:g} = {q['summa']:g}")
    lines.append("")
    lines.append(f"<b>JAMI: {d.get('jami_summa'):g} {d.get('valyuta')}</b>")
    if d.get("ogohlantirish"):
        lines.append(f"\n⚠️ {d['ogohlantirish']}")
    return "\n".join(lines)


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="ocr:confirm"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="ocr:cancel"),
    ]])


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, bot: Bot):
    # Faqat ops-ruxsatli foydalanuvchi; aks holda jim (boshqa handlerlar ko'rsin)
    if not is_ops_allowed(message.from_user.id):
        return

    wait = await message.answer("⏳ Rasmni o'qiyapman, biroz kuting (15-30s)...")
    photo = message.photo[-1]  # eng katta o'lcham
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
            tmp_path = tf.name
        await bot.download(photo, destination=tmp_path)
        # extract_from_image — sync subprocess (~15-30s). Event loop'ni
        # bloklamaslik uchun alohida thread'da.
        data = await asyncio.to_thread(extract_from_image, tmp_path)
    except (OcrCliError, OcrParseError) as e:
        await wait.edit_text(f"⚠️ O'qib bo'lmadi: {e}\nQayta urinib ko'ring yoki qo'lda kiriting.")
        return
    except Exception as e:
        logger.exception("ocr photo fail")
        await wait.edit_text(f"⚠️ Kutilmagan xato: {type(e).__name__}")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    await state.update_data(ocr_result=data)
    await wait.edit_text(_format_result(data), reply_markup=_confirm_kb())


@router.callback_query(F.data == "ocr:confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext):
    data = (await state.get_data()).get("ocr_result")
    if not data:
        await cb.answer("Ma'lumot topilmadi", show_alert=True)
        return
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Tasdiqlandi</b>", reply_markup=None)
    await cb.answer("Tasdiqlandi")


@router.callback_query(F.data == "ocr:cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext):
    await state.update_data(ocr_result=None)
    await cb.message.edit_text("❌ Bekor qilindi", reply_markup=None)
    await cb.answer()
