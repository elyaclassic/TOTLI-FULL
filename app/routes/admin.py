"""
Admin: backup (faqat admin).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.models.database import User
from app.deps import require_admin
from app.utils.backup import do_backup, cleanup_old_backups
from app.logging_config import get_logger

logger = get_logger("admin")
router = APIRouter(tags=["admin"])


@router.get("/admin/backup")
async def admin_backup(request: Request, current_user: User = Depends(require_admin)):
    """Baza faylini nusxalash (faqat admin). ?json=1 da JSON, aks holda bosh sahifaga."""
    try:
        path = do_backup()
        cleanup_old_backups(keep_count=30)
        logger.info("Backup yaratildi: %s", path)
        if request.query_params.get("json") == "1":
            return JSONResponse(content={"ok": True, "path": path})
        return RedirectResponse(url="/?backup=ok", status_code=303)
    except FileNotFoundError as e:
        logger.warning("Backup: %s", e)
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except Exception as e:
        logger.exception("Backup xatosi: %s", e)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
