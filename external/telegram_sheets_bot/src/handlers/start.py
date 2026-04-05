"""Minimal handlerlar — keyin kengaytirasiz."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Salom!\n\n"
        "🎤 Ovoz yuborsangiz: matnga aylantiriladi (OpenAI) va "
        "Google Sheets sozlangan bo'lsa jadvalga yoziladi.\n\n"
        "/help — yordam"
    )


@router.message(F.text)
async def echo_stub(message: Message) -> None:
    """Vaqtinchalik — matnni qaytaradi (Sheets ulanmaguncha)."""
    await message.answer(f"Siz yozdingiz: {message.text[:500]}")
