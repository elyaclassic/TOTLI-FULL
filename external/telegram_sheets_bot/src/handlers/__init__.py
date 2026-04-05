from aiogram import Router

from . import customers, ledger, reports, start, voice

router = Router()
router.include_router(start.router)
router.include_router(customers.router)
router.include_router(reports.router)
router.include_router(voice.router)
router.include_router(ledger.router)
