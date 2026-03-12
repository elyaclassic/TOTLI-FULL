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
)

router = APIRouter(tags=["delivery"])


@router.get("/delivery", response_class=HTMLResponse)
async def delivery_list(request: Request, db: Session = Depends(get_db)):
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
        "driver": driver,
        "locations": locations,
        "deliveries": deliveries,
        "page_title": f"Haydovchi: {driver.full_name}",
    })


@router.get("/map", response_class=HTMLResponse)
async def map_view(request: Request, db: Session = Depends(get_db)):
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
async def supervisor_dashboard(request: Request, db: Session = Depends(get_db)):
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
    stats = {
        "total_agents": total_agents,
        "active_agents": active_agents,
        "today_visits": today_visits,
        "today_orders": len(today_orders),
        "today_sales": today_sales_sum,
        "total_drivers": total_drivers,
        "pending_deliveries": pending_deliveries,
        "today_delivered": today_delivered,
    }
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    recent_visits = db.query(Visit).order_by(Visit.visit_date.desc()).limit(10).all()
    recent_deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).limit(10).all()
    return templates.TemplateResponse("supervisor/dashboard.html", {
        "request": request,
        "stats": stats,
        "agents": agents,
        "drivers": drivers,
        "agent_stats": agent_stats[:10],
        "recent_visits": recent_visits,
        "recent_deliveries": recent_deliveries,
        "page_title": "Supervayzer",
        "now": datetime.now(),
    })


@router.post("/delivery/add-driver")
async def add_driver(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(None),
    vehicle_type: str = Form(None),
    vehicle_number: str = Form(None),
    telegram_id: str = Form(None),
    db: Session = Depends(get_db),
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
):
    delivery = Delivery(
        driver_id=driver_id,
        order_number=order_number,
        delivery_address=delivery_address,
        notes=notes,
        status="pending",
    )
    db.add(delivery)
    db.commit()
    return RedirectResponse(url=f"/delivery/{driver_id}", status_code=303)
