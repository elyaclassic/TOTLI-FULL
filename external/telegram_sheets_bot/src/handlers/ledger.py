"""Matnli xabarlar — hisob-kitob qatoriga (Excel yoki Google Sheets)."""
import asyncio
import logging

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from src.config import EXCEL_FILE_PATH, GOOGLE_SHEET_ID, GOOGLE_SHEETS_CREDENTIALS_JSON, STORAGE_BACKEND
from src.services.excel_ledger import append_operation_row as append_operation_row_excel
from src.services.parse_operation import parse_operation_text
from src.services.sheets_append import append_operation_row as append_operation_row_sheets

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

    use_excel = STORAGE_BACKEND == "excel"
    sheet_ok = bool(GOOGLE_SHEETS_CREDENTIALS_JSON and GOOGLE_SHEET_ID)
    turi, summa, _ = parse_operation_text(text)

    if use_excel or sheet_ok:
        try:
            if use_excel:
                await asyncio.to_thread(
                    append_operation_row_excel,
                    text,
                    message.from_user.id,
                    message.from_user.username,
                    "matn",
                )
            else:
                await asyncio.to_thread(
                    append_operation_row_sheets,
                    text,
                    message.from_user.id,
                    message.from_user.username,
                    "matn",
                )
        except Exception as e:
            logger.exception("ledger append")
            await message.answer(f"❌ Saqlash: {str(e)[:400]}")
            return

    parts = [f"📝 <b>Matn:</b>\n{text[:3500]}"]
    if summa is not None:
        parts.append(f"\n📊 Summa: <b>{summa:,.0f}</b> (so'm)")
    if turi:
        parts.append(f"\n📌 Tur: <b>{turi}</b>")
    if use_excel:
        parts.append(f"\n\n✅ Excelga yozildi: <code>{EXCEL_FILE_PATH}</code>")
    elif sheet_ok:
        parts.append("\n\n✅ <b>Operatsiyalar</b> varag'iga yozildi.")
    else:
        parts.append(
            "\n\n⚠️ Saqlash ulanmagan — hozir faqat tahlil. "
            "<code>STORAGE_BACKEND=excel</code> yoki Sheets sozlang.",
        )
    await message.answer("\n".join(parts), parse_mode="HTML")
