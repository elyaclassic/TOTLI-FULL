"""Brending (logo) sozlamalari — admin paneldan logo yuklash/qaytarish."""
import io

from fastapi import APIRouter, Request, Depends, Form, File, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, AppSetting, User
from app.deps import require_admin
from app.services import branding_service

router = APIRouter(tags=["branding"])

_SLOTS = {"logo_main", "logo_circle"}


def _upsert_setting(db: Session, key: str, value):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


@router.get("/admin/branding")
async def branding_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    current = branding_service.resolve_branding(db)
    return templates.TemplateResponse(
        "admin/branding.html",
        {
            "request": request,
            "page_title": "Brending sozlamalari",
            "current_user": current_user,
            "current": current,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.post("/admin/branding/upload")
async def branding_upload(
    slot: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if slot not in _SLOTS:
        return RedirectResponse(url="/admin/branding?err=slot", status_code=303)

    filename = (image.filename or "").strip()
    if "." not in filename:
        return RedirectResponse(url="/admin/branding?err=ext", status_code=303)
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in branding_service.ALLOWED_EXTS:
        return RedirectResponse(url="/admin/branding?err=ext", status_code=303)

    contents = await image.read()
    if not contents or len(contents) > branding_service.MAX_SIZE_BYTES:
        return RedirectResponse(url="/admin/branding?err=size", status_code=303)

    try:
        from PIL import Image
        Image.open(io.BytesIO(contents)).verify()
    except Exception:
        return RedirectResponse(url="/admin/branding?err=invalid", status_code=303)

    new_name = branding_service.save_branding_image(slot, contents, ext)
    _upsert_setting(db, slot, new_name)
    branding_service.cleanup_old_branding(slot, keep=new_name)
    branding_service.invalidate_branding_cache()
    return RedirectResponse(url="/admin/branding?msg=saved", status_code=303)


@router.post("/admin/branding/reset")
async def branding_reset(
    slot: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if slot not in _SLOTS:
        return RedirectResponse(url="/admin/branding?err=slot", status_code=303)
    _upsert_setting(db, slot, None)
    branding_service.cleanup_old_branding(slot, keep="")
    branding_service.invalidate_branding_cache()
    return RedirectResponse(url="/admin/branding?msg=reset", status_code=303)
