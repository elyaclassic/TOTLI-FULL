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
    """Mobil ilova versiyasi tekshirish. Yangi versiya bo'lsa yangilash taklif qilinadi.

    DIQQAT: pubspec.yaml va main.dart (appVersion, appBuild) bilan **birga** yangilanishi shart.
    Aks holda yangilanish loop yoki "yangilanish bor" xabari noto'g'ri ishlaydi.
    """
    return {
        "version": "2.0.4",
        "build": 52,
        "force_update": False,
        "download_url": "/api/app/download",
        "changelog": "TOTLI HOLVA logotipi qo'shildi (login + ilova ikonasi)",
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
