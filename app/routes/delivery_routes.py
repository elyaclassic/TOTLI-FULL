"""
Yetkazib berish — haydovchilar, yetkazishlar, xarita, supervayzer.
"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from fastapi.responses import HTMLResponse, RedirectResponse
from app.core import templates
from app.models.database import (
    get_db,
    Driver,
    DriverLocation,
    Delivery,
    Agent,
    AgentLocation,
    Visit,
    Partner,
    PartnerLocation,
    Order,
    User,
)
from app.deps import require_admin, require_admin_or_manager
from sqlalchemy.orm import joinedload
from sqlalchemy import func

router = APIRouter(tags=["delivery"])


@router.get("/delivery", response_class=HTMLResponse)
async def delivery_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    drivers = db.query(Driver).all()
    today = datetime.now().date()
    for driver in drivers:
        driver.last_location = (
            db.query(DriverLocation)
            .filter(DriverLocation.driver_id == driver.id)
            .order_by(DriverLocation.recorded_at.desc())
            .first()
        )
        driver.today_deliveries = (
            db.query(Delivery)
            .filter(Delivery.driver_id == driver.id, Delivery.created_at >= today)
            .count()
        )
        driver.pending_deliveries = (
            db.query(Delivery).filter(Delivery.driver_id == driver.id, Delivery.status == "pending").count()
        )
    deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).limit(50).all()
    return templates.TemplateResponse("delivery/list.html", {
        "request": request,
        "current_user": current_user,
        "drivers": drivers,
        "deliveries": deliveries,
        "page_title": "Yetkazib berish",
    })


@router.post("/drivers/add")
async def driver_add(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    vehicle_number: str = Form(""),
    vehicle_type: str = Form(""),
    telegram_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    last_driver = db.query(Driver).order_by(Driver.id.desc()).first()
    code = f"DR{str((last_driver.id if last_driver else 0) + 1).zfill(3)}"
    driver = Driver(
        code=code,
        full_name=full_name,
        phone=phone,
        vehicle_number=vehicle_number,
        vehicle_type=vehicle_type,
        telegram_id=telegram_id,
        is_active=True,
    )
    db.add(driver)
    db.commit()
    return RedirectResponse(url="/delivery", status_code=303)


@router.get("/delivery/{driver_id}", response_class=HTMLResponse)
async def driver_detail(
    request: Request,
    driver_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Haydovchi topilmadi")
    locations = (
        db.query(DriverLocation)
        .filter(DriverLocation.driver_id == driver_id)
        .order_by(DriverLocation.recorded_at.desc())
        .limit(100)
        .all()
    )
    deliveries = (
        db.query(Delivery)
        .filter(Delivery.driver_id == driver_id)
        .order_by(Delivery.created_at.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse("delivery/detail.html", {
        "request": request,
        "current_user": current_user,
        "driver": driver,
        "locations": locations,
        "deliveries": deliveries,
        "page_title": f"Haydovchi: {driver.full_name}",
    })


@router.get("/map", response_class=HTMLResponse)
async def map_view(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    agent_markers = []
    for agent in agents:
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            agent_markers.append({
                "id": agent.id,
                "name": agent.full_name,
                "type": "agent",
                "lat": last_loc.latitude,
                "lng": last_loc.longitude,
                "time": last_loc.recorded_at.strftime("%H:%M"),
            })
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    driver_markers = []
    for driver in drivers:
        last_loc = (
            db.query(DriverLocation)
            .filter(DriverLocation.driver_id == driver.id)
            .order_by(DriverLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            driver_markers.append({
                "id": driver.id,
                "name": driver.full_name,
                "type": "driver",
                "lat": last_loc.latitude,
                "lng": last_loc.longitude,
                "time": last_loc.recorded_at.strftime("%H:%M"),
                "vehicle": driver.vehicle_number,
            })
    partner_locations = db.query(PartnerLocation).all()
    partner_markers = []
    for loc in partner_locations:
        partner = db.query(Partner).filter(Partner.id == loc.partner_id).first()
        if partner and loc.latitude and loc.longitude:
            partner_markers.append({
                "id": loc.partner_id,
                "name": partner.name,
                "type": "partner",
                "lat": loc.latitude,
                "lng": loc.longitude,
                "address": loc.address,
            })
    try:
        from app.config.maps_config import MAP_PROVIDER
        map_provider = MAP_PROVIDER
    except Exception:
        map_provider = "yandex"
    try:
        from app.config.maps_config import YANDEX_MAPS_API_KEY
        yandex_apikey = YANDEX_MAPS_API_KEY or ""
    except Exception:
        yandex_apikey = ""
    return templates.TemplateResponse("map/index.html", {
        "request": request,
        "current_user": current_user,
        "agents": agents,
        "drivers": drivers,
        "partner_locations": partner_locations,
        "agent_markers": agent_markers,
        "driver_markers": driver_markers,
        "partner_markers": partner_markers,
        "region_markers": [],
        "map_provider": map_provider,
        "yandex_maps_apikey": yandex_apikey,
        "page_title": "Xarita",
    })


@router.get("/supervisor", response_class=HTMLResponse)
async def supervisor_dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    today = datetime.now().date()
    total_agents = db.query(Agent).filter(Agent.is_active == True).count()
    active_agents = 0
    for agent in db.query(Agent).filter(Agent.is_active == True).all():
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id, AgentLocation.recorded_at >= today)
            .first()
        )
        if last_loc:
            active_agents += 1
    today_visits = db.query(Visit).filter(Visit.visit_date >= today).count()
    today_orders = db.query(Order).filter(Order.type == "sale", Order.date >= today).all()
    today_sales_sum = sum(o.total for o in today_orders)
    total_drivers = db.query(Driver).filter(Driver.is_active == True).count()
    pending_deliveries = db.query(Delivery).filter(Delivery.status == "pending").count()
    today_delivered = (
        db.query(Delivery)
        .filter(Delivery.status == "delivered", Delivery.delivered_at >= today)
        .count()
    )
    agent_stats = []
    for agent in db.query(Agent).filter(Agent.is_active == True).all():
        visits = db.query(Visit).filter(Visit.agent_id == agent.id, Visit.visit_date >= today).count()
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        agent_stats.append({
            "agent": agent,
            "visits": visits,
            "last_seen": last_loc.recorded_at if last_loc else None,
            "is_online": last_loc and (datetime.now() - last_loc.recorded_at).seconds < 600 if last_loc else False,
        })
    agent_stats.sort(key=lambda x: x["visits"], reverse=True)
    # O'tgan hafta vizitlar
    from datetime import timedelta
    week_ago = today - timedelta(days=7)
    visits_week = db.query(Visit).filter(Visit.visit_date >= week_ago).count()
    # Yo'ldagi yetkazishlar
    in_transit = db.query(Delivery).filter(Delivery.status.in_(["pending", "in_transit"])).count()
    stats = {
        "total_agents": total_agents,
        "active_agents": active_agents,
        "today_visits": today_visits,
        "visits_today": today_visits,
        "visits_week": visits_week,
        "today_orders": len(today_orders),
        "today_sales": today_sales_sum,
        "total_drivers": total_drivers,
        "pending_deliveries": pending_deliveries,
        "today_delivered": today_delivered,
        "delivered_today": today_delivered,
        "in_transit": in_transit,
    }
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    # Agent va driver markerlar (mini xarita uchun)
    agent_markers = []
    for agent in agents:
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            agent.last_location = last_loc
            agent_markers.append({
                "id": agent.id, "name": agent.full_name, "type": "agent",
                "lat": last_loc.latitude, "lng": last_loc.longitude,
                "time": last_loc.recorded_at.strftime("%H:%M"),
            })
    driver_markers = []
    for driver in drivers:
        last_loc = (
            db.query(DriverLocation)
            .filter(DriverLocation.driver_id == driver.id)
            .order_by(DriverLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            driver.last_location = last_loc
            driver_markers.append({
                "id": driver.id, "name": driver.full_name, "type": "driver",
                "lat": last_loc.latitude, "lng": last_loc.longitude,
                "time": last_loc.recorded_at.strftime("%H:%M"),
                "vehicle": driver.vehicle_number,
            })
    recent_visits = db.query(Visit).filter(Visit.visit_date >= today).order_by(Visit.visit_date.desc()).limit(20).all()
    recent_deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).limit(10).all()
    # Agent buyurtmalari (bugungi)
    agent_orders = (
        db.query(Order)
        .filter(Order.source == "agent", Order.date >= today)
        .order_by(Order.created_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse("supervisor/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": stats,
        "agents": agents,
        "drivers": drivers,
        "agent_markers": agent_markers,
        "driver_markers": driver_markers,
        "agent_stats": agent_stats[:10],
        "recent_visits": recent_visits,
        "recent_deliveries": recent_deliveries,
        "agent_orders": agent_orders,
        "page_title": "Supervayzer",
        "now": datetime.now(),
    })


@router.get("/supervisor/agent-orders", response_class=HTMLResponse)
async def supervisor_agent_orders(
    request: Request,
    status: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmalari alohida sahifa — tasdiqlash va yetkazishga berish."""
    q = db.query(Order).filter(Order.source == "agent").options(
        joinedload(Order.partner), joinedload(Order.items)
    )
    if status and status != "all":
        q = q.filter(Order.status == status)
    orders = q.order_by(Order.created_at.desc()).limit(100).all()
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    draft_count = db.query(func.count(Order.id)).filter(Order.source == "agent", Order.status == "draft").scalar() or 0
    return templates.TemplateResponse("supervisor/agent_orders.html", {
        "request": request,
        "current_user": current_user,
        "orders": orders,
        "drivers": drivers,
        "agents": agents,
        "current_status": status,
        "draft_count": draft_count,
        "page_title": "Agent buyurtmalari",
    })


@router.post("/supervisor/agent-orders/confirm/{order_id}")
async def supervisor_confirm_agent_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmasini tasdiqlash + haydovchiga yetkazish yaratish."""
    form = await request.form()
    driver_id_raw = form.get("driver_id", "").strip()
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    if order.status not in ("draft",):
        return RedirectResponse(url="/supervisor/agent-orders?error=already_confirmed", status_code=303)
    # Buyurtmani tasdiqlash
    order.status = "confirmed"
    order.user_id = current_user.id
    db.flush()
    # Haydovchiga yetkazish yaratish
    if driver_id_raw and driver_id_raw.isdigit():
        driver_id = int(driver_id_raw)
        driver = db.query(Driver).filter(Driver.id == driver_id, Driver.is_active == True).first()
        if driver:
            # Partner geolokatsiyasi
            partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
            address = partner.address or "" if partner else ""
            lat = partner.latitude if partner else None
            lng = partner.longitude if partner else None
            # Delivery raqami
            today = datetime.now()
            prefix = f"DLV-{today.strftime('%Y%m%d')}"
            last = db.query(Delivery).filter(Delivery.number.like(f"{prefix}%")).order_by(Delivery.id.desc()).first()
            try:
                seq = int(last.number.split("-")[-1]) + 1 if last and last.number else 1
            except Exception:
                seq = 1
            delivery = Delivery(
                number=f"{prefix}-{seq:03d}",
                driver_id=driver_id,
                order_id=order.id,
                order_number=order.number,
                delivery_address=address,
                latitude=lat,
                longitude=lng,
                planned_date=today,
                notes=f"Mijoz: {partner.name if partner else ''}, Tel: {partner.phone if partner else ''}",
                status="pending",
            )
            db.add(delivery)
    db.commit()
    return RedirectResponse(url="/supervisor/agent-orders", status_code=303)


@router.post("/supervisor/agent-orders/reject/{order_id}")
async def supervisor_reject_agent_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmasini bekor qilish."""
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    order.status = "cancelled"
    db.commit()
    return RedirectResponse(url="/supervisor/agent-orders", status_code=303)


@router.post("/delivery/add-driver")
async def add_driver(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(None),
    vehicle_type: str = Form(None),
    vehicle_number: str = Form(None),
    telegram_id: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    last_driver = db.query(Driver).order_by(Driver.id.desc()).first()
    code = f"DR{str((last_driver.id if last_driver else 0) + 1).zfill(3)}"
    driver = Driver(
        code=code,
        full_name=full_name,
        phone=phone,
        vehicle_type=vehicle_type,
        vehicle_number=vehicle_number,
        telegram_id=telegram_id,
        is_active=True,
    )
    db.add(driver)
    db.commit()
    return RedirectResponse(url="/delivery", status_code=303)


@router.post("/delivery/add-order")
async def add_delivery_order(
    request: Request,
    driver_id: int = Form(...),
    order_number: str = Form(...),
    delivery_address: str = Form(...),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    # Yetkazish raqami generatsiya: DLV-YYYYMMDD-NNN
    today = datetime.now()
    prefix = f"DLV-{today.strftime('%Y%m%d')}"
    last = db.query(Delivery).filter(Delivery.number.like(f"{prefix}%")).order_by(Delivery.id.desc()).first()
    if last and last.number:
        try:
            seq = int(last.number.split("-")[-1]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1
    delivery_number = f"{prefix}-{seq:03d}"
    # order_id topish (agar mavjud bo'lsa)
    order = db.query(Order).filter(Order.number == order_number).first()
    delivery = Delivery(
        number=delivery_number,
        driver_id=driver_id,
        order_id=order.id if order else None,
        order_number=order_number,
        delivery_address=delivery_address,
        planned_date=today,
        notes=notes,
        status="pending",
    )
    db.add(delivery)
    db.commit()
    return RedirectResponse(url=f"/delivery/{driver_id}", status_code=303)
