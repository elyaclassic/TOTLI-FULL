"""
Admin: backup, oy yopish (faqat admin).
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.models.database import (
    get_db, User, ClosedPeriod, Stock, CashRegister, Partner, Order, Purchase,
    Production, Payment, ExpenseDoc,
)
from app.core import templates
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
            return JSONResponse(content={"ok": True})
        return RedirectResponse(url="/?backup=ok", status_code=303)
    except FileNotFoundError as e:
        logger.warning("Backup: %s", e)
        return JSONResponse(status_code=404, content={"ok": False, "error": "Backup fayli topilmadi"})
    except Exception as e:
        logger.exception("Backup xatosi: %s", e)
        return JSONResponse(status_code=500, content={"ok": False, "error": "Backup bajarishda xatolik"})


# ==========================================
# OY YOPISH
# ==========================================

def is_period_closed(db: Session, date_obj) -> bool:
    """Berilgan sana yopilgan davrga tegishli ekanligini tekshiradi."""
    if not date_obj:
        return False
    if isinstance(date_obj, str):
        period = date_obj[:7]
    else:
        period = date_obj.strftime("%Y-%m")
    return db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first() is not None


@router.get("/admin/periods", response_class=HTMLResponse)
async def admin_periods(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Yopilgan davrlar ro'yxati."""
    periods = db.query(ClosedPeriod).order_by(ClosedPeriod.period.desc()).all()
    now = datetime.now()
    current_period = now.strftime("%Y-%m")
    # Joriy oy yopilganmi
    current_closed = any(p.period == current_period for p in periods)
    # Oldingi oy
    if now.month == 1:
        prev_period = f"{now.year - 1}-12"
    else:
        prev_period = f"{now.year}-{now.month - 1:02d}"
    prev_closed = any(p.period == prev_period for p in periods)
    # Ochiq draft hujjatlar soni (oldingi oy)
    draft_sales = db.query(Order).filter(
        Order.status == "draft",
        Order.date >= prev_period + "-01",
        Order.date < current_period + "-01",
    ).count()
    draft_purchases = db.query(Purchase).filter(
        Purchase.status == "draft",
        Purchase.date >= prev_period + "-01",
        Purchase.date < current_period + "-01",
    ).count()
    return templates.TemplateResponse("admin/periods.html", {
        "request": request,
        "current_user": current_user,
        "periods": periods,
        "current_period": current_period,
        "prev_period": prev_period,
        "prev_closed": prev_closed,
        "current_closed": current_closed,
        "draft_sales": draft_sales,
        "draft_purchases": draft_purchases,
        "page_title": "Oy yopish",
    })


@router.post("/admin/periods/close")
async def admin_close_period(
    request: Request,
    period: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Oyni yopish — snapshot saqlash va yozuvni bloklash."""
    # S5 audit fix: period format YYYY-MM bo'lishi kerak (XSS/injection oldini olish)
    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        return RedirectResponse(url="/admin/periods?error=invalid_period", status_code=303)
    existing = db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first()
    if existing:
        return RedirectResponse(url="/admin/periods?error=already_closed", status_code=303)
    # Snapshot: stock qoldiqlari
    stocks = db.query(Stock).filter(Stock.quantity > 0.001).all()
    stock_snap = {}
    for s in stocks:
        wh = str(s.warehouse_id)
        if wh not in stock_snap:
            stock_snap[wh] = {}
        stock_snap[wh][str(s.product_id)] = round(s.quantity, 3)
    # Snapshot: kassa balanslari
    cash_regs = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    cash_snap = {}
    for cr in cash_regs:
        cash_snap[str(cr.id)] = round(float(cr.balance or 0), 2)
    # Snapshot: mijoz qarzlari
    partners = db.query(Partner).filter(Partner.balance != 0).all()
    partner_snap = {}
    for p in partners:
        partner_snap[str(p.id)] = round(float(p.balance or 0), 2)
    cp = ClosedPeriod(
        period=period,
        closed_at=datetime.now(),
        closed_by=current_user.id,
        note=note or None,
        snapshot_stock=json.dumps(stock_snap),
        snapshot_cash=json.dumps(cash_snap),
        snapshot_partner_debt=json.dumps(partner_snap),
    )
    db.add(cp)
    db.commit()
    logger.info("Oy yopildi: %s (user=%s)", period, current_user.username)
    return RedirectResponse(url="/admin/periods?closed=" + period, status_code=303)


@router.post("/admin/periods/reopen")
async def admin_reopen_period(
    request: Request,
    period: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Yopilgan oyni qayta ochish."""
    # S5 audit fix: period format validation
    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        return RedirectResponse(url="/admin/periods?error=invalid_period", status_code=303)
    cp = db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first()
    if not cp:
        return RedirectResponse(url="/admin/periods?error=not_found", status_code=303)
    logger.info("Oy qayta ochildi: %s (user=%s, sabab=%s)", period, current_user.username, note)
    db.delete(cp)
    db.commit()
    return RedirectResponse(url="/admin/periods?reopened=" + period, status_code=303)
