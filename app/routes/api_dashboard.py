"""
API — dashboard endpointlari (stats, products, partners, locations, notifications).

Tier C2 2-bosqich: api_routes.py dan ajratib olindi.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import (
    get_db, User, Order, Product, Partner, CashRegister,
    Agent, Driver, AgentLocation, DriverLocation,
)
from app.deps import get_current_user
from app.utils.rate_limit import check_api_rate_limit
from app.utils.auth import get_user_from_token
from app.utils.notifications import get_unread_count, get_user_notifications, mark_as_read

router = APIRouter(prefix="/api", tags=["api-dashboard"])


@router.get("/stats")
async def api_stats(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    today = datetime.now().date()
    today_sales = db.query(Order).filter(Order.type == "sale", Order.date >= today).all()
    cash = db.query(CashRegister).first()
    return {
        "today_sales": sum(o.total for o in today_sales),
        "today_orders": len(today_sales),
        "cash_balance": cash.balance if cash else 0,
        "products_count": db.query(Product).count(),
        "partners_count": db.query(Partner).count(),
    }


@router.get("/products")
async def api_products(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    products = db.query(Product).filter(Product.is_active == True).all()
    return [{"id": p.id, "name": p.name, "code": p.code, "price": p.sale_price} for p in products]


@router.get("/partners")
async def api_partners(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    partners = db.query(Partner).filter(Partner.is_active == True).all()
    return [{"id": p.id, "name": p.name, "balance": p.balance} for p in partners]


@router.get("/agents/locations")
async def get_agents_locations(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    # Subquery: har bir agent uchun oxirgi location ID
    latest_loc_sq = (
        db.query(
            AgentLocation.agent_id,
            func.max(AgentLocation.id).label("max_id"),
        )
        .group_by(AgentLocation.agent_id)
        .subquery()
    )
    rows = (
        db.query(Agent, AgentLocation)
        .join(latest_loc_sq, Agent.id == latest_loc_sq.c.agent_id)
        .join(AgentLocation, AgentLocation.id == latest_loc_sq.c.max_id)
        .filter(Agent.is_active == True)
        .all()
    )
    return [
        {
            "id": agent.id,
            "name": agent.full_name,
            "code": agent.code,
            "lat": loc.latitude,
            "lng": loc.longitude,
            "time": loc.recorded_at.isoformat(),
            "battery": getattr(loc, "battery", None),
        }
        for agent, loc in rows
    ]


@router.get("/drivers/locations")
async def get_drivers_locations(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    # Subquery: har bir driver uchun oxirgi location ID
    latest_loc_sq = (
        db.query(
            DriverLocation.driver_id,
            func.max(DriverLocation.id).label("max_id"),
        )
        .group_by(DriverLocation.driver_id)
        .subquery()
    )
    rows = (
        db.query(Driver, DriverLocation)
        .join(latest_loc_sq, Driver.id == latest_loc_sq.c.driver_id)
        .join(DriverLocation, DriverLocation.id == latest_loc_sq.c.max_id)
        .filter(Driver.is_active == True)
        .all()
    )
    return [
        {
            "id": driver.id,
            "name": driver.full_name,
            "code": driver.code,
            "vehicle": driver.vehicle_number,
            "lat": loc.latitude,
            "lng": loc.longitude,
            "time": loc.recorded_at.isoformat(),
            "speed": getattr(loc, "speed", None),
        }
        for driver, loc in rows
    ]


@router.get("/notifications/unread")
async def api_notifications_unread(
    token: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """O'qilmagan bildirishnomalar soni va oxirgisi (cookie yoki ?token= orqali)."""
    user = current_user
    if not user and token:
        user_data = get_user_from_token(token)
        if user_data:
            user = db.query(User).filter(User.id == user_data["user_id"], User.is_active == True).first()
    if not user:
        return {"unread_count": 0, "last": None}
    count = get_unread_count(db, user.id)
    last_list = get_user_notifications(db, user.id, unread_only=True, limit=1)
    last = None
    if last_list:
        n = last_list[0]
        last = {
            "id": n.id,
            "title": n.title or "",
            "message": n.message or "",
            "priority": n.priority or "normal",
            "action_url": n.action_url or None,
            "type": n.notification_type or "info",
        }
    return {"unread_count": count, "last": last}


@router.post("/notifications/{notification_id}/read")
async def api_notification_mark_read(
    notification_id: int,
    token: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bildirishnomani o'qilgan deb belgilash (cookie yoki ?token=)."""
    user = current_user
    if not user and token:
        user_data = get_user_from_token(token)
        if user_data:
            user = db.query(User).filter(User.id == user_data["user_id"], User.is_active == True).first()
    if not user:
        return {"ok": False}
    mark_as_read(db, notification_id)
    return {"ok": True}
