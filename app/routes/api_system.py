"""
API — tizim endpointlari (PWA config, app versiya, APK download).

Tier C2 1-bosqich: api_routes.py:54-82 dan ajratib olindi.
"""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api", tags=["api-system"])


@router.get("/pwa/config")
async def pwa_config():
    """PWA/mobil ilova uchun API asosiy manzil.
    Env: PWA_API_BASE_URL (bo'sh bo'lsa brauzer origin ishlatiladi)."""
    return {"apiBaseUrl": os.getenv("PWA_API_BASE_URL", "").strip()}


@router.get("/app/version")
async def app_version():
    """Mobil ilova versiyasi tekshirish. Yangi versiya bo'lsa yangilash taklif qilinadi."""
    return {
        "version": "1.8.3",
        "build": 43,
        "force_update": True,
        "download_url": "/api/app/download",
        "changelog": "Vizitlar va yetkazishlar sana filtri, kunlar bo'yicha ko'rish",
    }


@router.get("/app/download")
async def app_download():
    """APK faylni to'g'ri MIME type bilan yuklash."""
    apk_path = os.path.join("app", "static", "totli-agent.apk")
    if not os.path.exists(apk_path):
        raise HTTPException(status_code=404, detail="APK topilmadi")
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename="totli-agent.apk",
    )
