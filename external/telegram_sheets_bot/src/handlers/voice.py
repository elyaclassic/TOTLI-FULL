"""Ovozli xabar: yuklash → Whisper → Excel yoki Google Sheets."""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import Message

from src.access import AllowedUserFilter
from src.config import EXCEL_FILE_PATH, GOOGLE_SHEET_ID, GOOGLE_SHEETS_CREDENTIALS_JSON, STORAGE_BACKEND
from src.services.excel_ledger import append_voice_row as append_voice_row_excel
from src.services.parse_operation import parse_operation_text
from src.services.sheets_append import append_voice_row as append_voice_row_sheets
from src.services.transcribe import can_transcribe, transcribe_audio_file

router = Router()
router.message.filter(AllowedUserFilter())
logger = logging.getLogger(__name__)


@router.message(F.voice)
async def on_voice(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return

    if not can_transcribe():
        await message.answer(
            "Ovozni matnga o'tkazish uchun <b>bittasi</b> kerak:\n\n"
            "🆓 <b>Bepul (sizning kompyuteringizda):</b>\n"
            "<code>pip install faster-whisper</code>\n"
            "<code>OPENAI_API_KEY</code> ni .env da bo'sh qoldiring yoki "
            "<code>TRANSCRIBE_BACKEND=local</code>\n"
            "(birinchi marta model yuklanadi, 300–1500 MB).\n\n"
            "💳 <b>OpenAI (pullik):</b> <code>OPENAI_API_KEY</code> qo'shing.\n\n"
            "Saqlash uchun: <code>STORAGE_BACKEND=excel</code> yoki "
            "<code>GOOGLE_SHEETS_CREDENTIALS_JSON</code> + <code>GOOGLE_SHEET_ID</code>.",
            parse_mode="HTML",
        )
        return

    status = await message.answer("⏳ Ovoz yuklanmoqda...")
    tmp_path: Path | None = None
    try:
        tg_file = await bot.get_file(message.voice.file_id)
        ext = Path(tg_file.file_path or "file.ogg").suffix or ".ogg"
        fd, name = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        tmp_path = Path(name)

        await bot.download_file(tg_file.file_path, destination=tmp_path)

        await status.edit_text("⏳ Matnga aylantirilmoqda (Whisper — birinchi marta uzoqroq bo'lishi mumkin)...")
        text = await transcribe_audio_file(tmp_path)

        use_excel = STORAGE_BACKEND == "excel"
        sheet_ok = bool(GOOGLE_SHEETS_CREDENTIALS_JSON and GOOGLE_SHEET_ID)
        if use_excel or sheet_ok:
            await status.edit_text("⏳ Saqlanmoqda...")
            if use_excel:
                await asyncio.to_thread(
                    append_voice_row_excel,
                    text,
                    message.from_user.id,
                    message.from_user.username,
                )
            else:
                await asyncio.to_thread(
                    append_voice_row_sheets,
                    text,
                    message.from_user.id,
                    message.from_user.username,
                )

        turi, summa, _ = parse_operation_text(text)
        lines = [f"📝 <b>Matn:</b>\n{text}"]
        if summa is not None:
            lines.append(f"\n📊 Summa: <b>{summa:,.0f}</b> so'm")
        if turi:
            lines.append(f"\n📌 Tur: <b>{turi}</b>")
        if use_excel:
            lines.append(f"\n\n✅ Excelga yozildi: <code>{EXCEL_FILE_PATH}</code>")
        elif sheet_ok:
            lines.append("\n\n✅ <b>Operatsiyalar</b> varag'iga yozildi.")
        else:
            lines.append(
                "\n⚠️ Saqlash ulanmagan. Excel uchun <code>STORAGE_BACKEND=excel</code>, "
                "yoki Sheets uchun credentials va <code>GOOGLE_SHEET_ID</code> ni to'ldiring.",
            )
        await status.edit_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception("on_voice")
        err = str(e)[:800]
        try:
            await status.edit_text(f"❌ Xato: {err}")
        except Exception:
            await message.answer(f"❌ Xato: {err}")
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
