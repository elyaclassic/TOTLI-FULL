"""Matnli xabarlar — hisob-kitob qatoriga (Google Sheets)."""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from src.config import GOOGLE_SHEET_ID, GOOGLE_SHEETS_CREDENTIALS_JSON
from src.services.parse_operation import parse_operation_text
from src.services.sheets_append import append_operation_row

router = Router()
logger = logging.getLogger(__name__)


class TextNotCommand(BaseFilter):
    """Slash bilan boshlanmaydigan matn."""

    async def __call__(self, message: Message) -> bool:
        t = message.text or ""
        return bool(t.strip()) and not t.startswith("/")


@router.message(TextNotCommand())
async def on_text_ledger(message: Message) -> None:
    text = (message.text or "").strip()
    if not message.from_user:
        return

    sheet_ok = bool(GOOGLE_SHEETS_CREDENTIALS_JSON and GOOGLE_SHEET_ID)
    turi, summa, _ = parse_operation_text(text)

    if sheet_ok:
        try:
            await asyncio.to_thread(
                append_operation_row,
                text,
                message.from_user.id,
                message.from_user.username,
                "matn",
            )
        except Exception as e:
            logger.exception("ledger append")
            await message.answer(f"❌ Sheets: {str(e)[:400]}")
            return

    parts = [f"📝 <b>Matn:</b>\n{text[:3500]}"]
    if summa is not None:
        parts.append(f"\n📊 Summa: <b>{summa:,.0f}</b> (so'm)")
    if turi:
        parts.append(f"\n📌 Tur: <b>{turi}</b>")
    if sheet_ok:
        parts.append("\n\n✅ <b>Operatsiyalar</b> varag'iga yozildi.")
    else:
        parts.append(
            "\n\n⚠️ Google Sheets ulanmagan — faqat tahlil. "
            "<code>.env</code> da credentials va SHEET_ID.",
        )
    await message.answer("\n".join(parts), parse_mode="HTML")
