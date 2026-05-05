"""
API — tizim endpointlari (PWA config, app versiya, APK download).

Tier C2 1-bosqich: api_routes.py:54-82 dan ajratib olindi.
"""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api", tags=["api-system"])


def _is_local_request(request: Request) -> bool:
    """Lokal tarmoqdan so'rovlar (localhost yoki internal LAN)."""
    client = request.client
    if not client:
        return False
    host = client.host
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    # Internal LAN (10.x.x.x, 192.168.x.x, 172.16-31.x.x)
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("169.254."):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (ValueError, IndexError):
            pass
    return False


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
        "version": "2.0.12",
        "build": 60,
        "force_update": False,
        "download_url": "/api/app/download",
        "changelog": "Vizit ekranidagi 'Vozvrat' va 'Obmen' tugmalari endi tarixsiz ham ishlaydi (parent buyurtma talab qilmaydi). Mahsulot+miqdor+narxni manual kiritasiz.",
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


@router.post("/internal/notify-owner")
async def internal_notify_owner(request: Request):
    """Localhost'dan owner ga Telegram orqali xabar yuborish.

    Claude Code Stop hook tomonidan chaqiriladi - har Claude javobini Telegramga push qilish uchun.
    Faqat localhost (127.0.0.1) qabul qilinadi - tashqi tarmoqdan kirish yo'q.

    Body (JSON yoki form): {"text": "..."}
    Qaytaradi: {"ok": true} agar yuborildi, yoki xato.
    """
    if not _is_local_request(request):
        return JSONResponse({"ok": False, "error": "Faqat localhost"}, status_code=403)
    text = ""
    try:
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            data = await request.json()
            text = (data.get("text") or "").strip()
        else:
            form = await request.form()
            text = (form.get("text") or "").strip()
    except Exception:
        return JSONResponse({"ok": False, "error": "Body o'qib bo'lmadi"}, status_code=400)
    if not text:
        return JSONResponse({"ok": False, "error": "text bo'sh"}, status_code=400)
    try:
        from app.bot.claude_remote import notify_owner
        ok = notify_owner(text)
        return {"ok": bool(ok)}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
