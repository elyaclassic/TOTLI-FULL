from aiogram import Router

from . import ledger, start, voice

router = Router()
router.include_router(start.router)
router.include_router(voice.router)
router.include_router(ledger.router)
