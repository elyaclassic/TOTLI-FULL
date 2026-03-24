"""Audit log — operatsiyalar tarixi."""
from typing import Optional
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.core import templates
from app.models.database import get_db, User, AuditLog
from app.deps import require_admin

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_class=HTMLResponse)
async def audit_log_page(
    request: Request,
    date_from: str = None,
    date_to: str = None,
    action: str = None,
    entity_type: str = None,
    user_id: Optional[str] = None,
    q: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Audit log sahifasi — faqat admin."""
    today = datetime.now()
    if not date_from:
        date_from = today.strftime("%Y-%m-%d")
    if not date_to:
        date_to = today.strftime("%Y-%m-%d")
    try:
        dt_from = datetime.strptime(date_from, "%Y-%m-%d")
        dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except (ValueError, TypeError):
        dt_from = today.replace(hour=0, minute=0, second=0)
        dt_to = today.replace(hour=23, minute=59, second=59)

    query = db.query(AuditLog).filter(
        AuditLog.timestamp >= dt_from,
        AuditLog.timestamp <= dt_to,
    )
    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    uid = None
    if user_id and str(user_id).strip().isdigit():
        uid = int(user_id)
        query = query.filter(AuditLog.user_id == uid)
    if q:
        query = query.filter(
            AuditLog.details.ilike(f"%{q}%") |
            AuditLog.entity_number.ilike(f"%{q}%") |
            AuditLog.user_name.ilike(f"%{q}%")
        )
    logs = query.order_by(AuditLog.timestamp.desc()).limit(500).all()
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()

    return templates.TemplateResponse("audit/index.html", {
        "request": request,
        "logs": logs,
        "users": users,
        "date_from": date_from,
        "date_to": date_to,
        "current_action": action or "",
        "current_entity_type": entity_type or "",
        "current_user_id": uid,
        "current_q": q or "",
        "current_user": current_user,
        "page_title": "Audit log — operatsiyalar tarixi",
    })
