"""Buyurtma holati katta-ekran board — sahifa + snapshot API (admin/menejer)."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, User
from app.deps import require_auth
from app.services.board_service import build_board_snapshot

router = APIRouter(prefix="/sales", tags=["board"])


@router.get("/board", response_class=HTMLResponse)
async def order_board_page(request: Request, current_user: User = Depends(require_auth)):
    """To'liq-ekran buyurtma board sahifasi."""
    return templates.TemplateResponse("board/order_board.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Buyurtma board",
    })


@router.get("/board/data", response_class=JSONResponse)
async def order_board_data(db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    """Joriy snapshot (JSON) — boshlang'ich yuklash + qayta-sinxron uchun."""
    return build_board_snapshot(db)
