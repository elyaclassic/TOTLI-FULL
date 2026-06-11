"""OCR web endpoint — rasm upload → strukturalangan JSON.

Natija HECH QACHON avtomatik saqlanmaydi — front-end forma uni ko'rsatadi,
foydalanuvchi tahrirlab odatdagi 'Saqlash' bilan yozadi.
"""
import os
import tempfile
import logging

from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import JSONResponse

from app.deps import require_auth
from app.models.database import User
from app.services.ocr_service import extract_from_image, OcrCliError, OcrParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["ocr"])

_ALLOWED = {"image/jpeg", "image/png", "image/webp"}
_MAX_BYTES = 12 * 1024 * 1024  # 12 MB


@router.post("/parse")
async def ocr_parse(
    file: UploadFile = File(...),
    current_user: User = Depends(require_auth),
):
    """Rasmni Claude Vision orqali o'qib strukturalangan JSON qaytaradi."""
    if file.content_type not in _ALLOWED:
        return JSONResponse({"ok": False, "error": "Faqat JPG/PNG/WEBP rasm"}, status_code=200)

    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        return JSONResponse({"ok": False, "error": "Rasm juda katta (>12MB)"}, status_code=200)
    if not raw:
        return JSONResponse({"ok": False, "error": "Bo'sh fayl"}, status_code=200)

    suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
            tf.write(raw)
            tmp_path = tf.name
        data = extract_from_image(tmp_path)
        return JSONResponse({"ok": True, "data": data}, status_code=200)
    except (OcrCliError, OcrParseError) as e:
        logger.warning(f"[ocr] parse fail: {e}")
        return JSONResponse(
            {"ok": False, "error": f"O'qib bo'lmadi: {e}. Qayta urinib ko'ring yoki qo'lda kiriting."},
            status_code=200,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
