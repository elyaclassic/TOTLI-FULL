from aiogram import Router

from . import start, voice

router = Router()
router.include_router(start.router)
router.include_router(voice.router)
