"""Expert botlarni ishga tushirish va to'xtatish.

Har ekspert uchun token .env'da EXPERT_<NOMI>_TOKEN shaklida.
Masalan: EXPERT_NOSIR_TOKEN, EXPERT_ANVAR_TOKEN, ...
Token yo'q bo'lsa — o'tkazib yuboriladi.
"""
from __future__ import annotations

import logging
import os

from app.bot.expert_bots.expert_bot import ExpertBot

logger = logging.getLogger(__name__)

# Ekspert nomi → env var nomi
EXPERT_ENV_VARS: dict[str, str] = {
    "Nosir": "EXPERT_NOSIR_TOKEN",
    "Rustam": "EXPERT_RUSTAM_TOKEN",
    "Diyor": "EXPERT_DIYOR_TOKEN",
    "Kamila": "EXPERT_KAMILA_TOKEN",
    "Bekzod": "EXPERT_BEKZOD_TOKEN",
    "Anvar": "EXPERT_ANVAR_TOKEN",
    "Sherzod": "EXPERT_SHERZOD_TOKEN",
    "Nodira": "EXPERT_NODIRA_TOKEN",
    "Jahongir": "EXPERT_JAHONGIR_TOKEN",
    "Alisher": "EXPERT_ALISHER_TOKEN",
    "Dilshoda": "EXPERT_DILSHODA_TOKEN",
}

_bots: list[ExpertBot] = []


async def start_expert_bots() -> None:
    global _bots
    for name, env_var in EXPERT_ENV_VARS.items():
        token = (os.environ.get(env_var) or "").strip()
        if not token:
            continue
        bot = ExpertBot(expert_name=name, token=token)
        _bots.append(bot)
        await bot.start()


async def stop_expert_bots() -> None:
    for bot in _bots:
        await bot.stop()
    _bots.clear()
