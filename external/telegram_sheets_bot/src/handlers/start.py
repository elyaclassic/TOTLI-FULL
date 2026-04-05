"""Minimal handlerlar — keyin kengaytirasiz."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Salom!\n\n"
        "🎤 Ovoz yoki matn: hisob-kitob yozuvi (summa, kirim/chiqim) "
        "Excel yoki Google Sheets <b>Operatsiyalar</b> varag'iga yoziladi.\n\n"
        "/help — yordam"
    )
