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
    AgentPayment,
    Payment,
    CashRegister,
    Product,
    Stock,
)
from app.deps import require_admin, require_admin_or_manager
from app.services.stock_service import create_stock_movement, delete_stock_movements_for_document, apply_sale_stock_deduction
from app.constants import QUERY_LIMIT_DEFAULT, QUERY_LIMIT_HISTORY
from urllib.parse import quote
from sqlalchemy.orm import joinedload
from sqlalchemy import func

router = APIRouter(tags=["delivery"])


@router.get("/delivery", response_class=HTMLResponse)
async def delivery_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    drivers = db.query(Driver).all()
    today = datetime.now().date()
    driver_ids = [d.id for d in drivers]
    # Batch loadlar (3N -> 3 ta umumiy query)
    last_loc_map: dict = {}
    today_count_map: dict = {}
    pending_count_map: dict = {}
    if driver_ids:
        # Oxirgi DriverLocation per driver — MAX(id) GROUP BY + load
        max_loc_ids = [
            r.max_id for r in
            db.query(DriverLocation.driver_id, func.max(DriverLocation.id).label("max_id"))
            .filter(DriverLocation.driver_id.in_(driver_ids))
            .group_by(DriverLocation.driver_id).all()
            if r.max_id
        ]
        if max_loc_ids:
            for loc in db.query(DriverLocation).filter(DriverLocation.id.in_(max_loc_ids)).all():
                last_loc_map[loc.driver_id] = loc
        # Bugungi yetkazishlar soni
        for r in (
            db.query(Delivery.driver_id, func.count(Delivery.id).label("cnt"))
            .filter(Delivery.driver_id.in_(driver_ids), Delivery.created_at >= today)
            .group_by(Delivery.driver_id).all()
        ):
            today_count_map[r.driver_id] = r.cnt
        # Pending yetkazishlar soni
        for r in (
            db.query(Delivery.driver_id, func.count(Delivery.id).label("cnt"))
            .filter(Delivery.driver_id.in_(driver_ids), Delivery.status == "pending")
            .group_by(Delivery.driver_id).all()
        ):
            pending_count_map[r.driver_id] = r.cnt
    for driver in drivers:
        driver.last_location = last_loc_map.get(driver.id)
        driver.today_deliveries = today_count_map.get(driver.id, 0)
        driver.pending_deliveries = pending_count_map.get(driver.id, 0)
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
        "yandex_maps_apikey": _get_yandex_apikey(),
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
    # Agent dict (id -> name)
    agent_dict = {a.id: a.full_name for a in agents}
    # Partner mijozlar + agent statistika
    all_partners = db.query(Partner).filter(Partner.is_active == True).all()
    # Agent bo'yicha mijozlar soni (jami va xaritadagi)
    agent_partner_total = {}
    for p in all_partners:
        aid = p.agent_id or 0
        agent_partner_total[aid] = agent_partner_total.get(aid, 0) + 1

    partner_markers = []
    agent_partner_on_map = {}
    seen_ids = set()
    # 1) Partner.latitude/longitude dan
    for p in all_partners:
        if p.latitude and p.longitude:
            aid = p.agent_id or 0
            agent_partner_on_map[aid] = agent_partner_on_map.get(aid, 0) + 1
            seen_ids.add(p.id)
            partner_markers.append({
                "id": p.id, "name": p.name, "type": "partner",
                "lat": p.latitude, "lng": p.longitude,
                "address": p.address or "",
                "agent_id": aid,
                "agent_name": agent_dict.get(aid, "Tayinlanmagan"),
            })
    # 2) PartnerLocation dan (Partner.lat bo'sh bo'lganlar)
    partner_locations = db.query(PartnerLocation).all()
    for loc in partner_locations:
        if loc.partner_id in seen_ids or not loc.latitude or not loc.longitude:
            continue
        partner = db.query(Partner).filter(Partner.id == loc.partner_id).first()
        if partner:
            aid = partner.agent_id or 0
            agent_partner_on_map[aid] = agent_partner_on_map.get(aid, 0) + 1
            seen_ids.add(partner.id)
            partner_markers.append({
                "id": loc.partner_id, "name": partner.name, "type": "partner",
                "lat": loc.latitude, "lng": loc.longitude,
                "address": loc.address or partner.address or "",
                "agent_id": aid,
                "agent_name": agent_dict.get(aid, "Tayinlanmagan"),
            })
    # Agent ro'yxati (chap panel uchun)
    agent_list = []
    for a in agents:
        on_map = agent_partner_on_map.get(a.id, 0)
        total = agent_partner_total.get(a.id, 0)
        if total > 0:
            agent_list.append({"id": a.id, "name": a.full_name, "on_map": on_map, "total": total})
    # Tayinlanmagan
    unassigned_on_map = agent_partner_on_map.get(0, 0)
    unassigned_total = agent_partner_total.get(0, 0)
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
        "agent_list": agent_list,
        "unassigned_on_map": unassigned_on_map,
        "unassigned_total": unassigned_total,
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
            agent.is_online = (datetime.now() - last_loc.recorded_at).total_seconds() < 600
            if last_loc.latitude is not None and last_loc.longitude is not None:
                agent_markers.append({
                    "id": agent.id,
                    "name": agent.full_name,
                    "type": "agent",
                    "lat": float(last_loc.latitude),
                    "lng": float(last_loc.longitude),
                    "time": last_loc.recorded_at.strftime("%H:%M"),
                })
        else:
            agent.is_online = False
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
            if last_loc.latitude is not None and last_loc.longitude is not None:
                driver_markers.append({
                    "id": driver.id,
                    "name": driver.full_name,
                    "type": "driver",
                    "lat": float(last_loc.latitude),
                    "lng": float(last_loc.longitude),
                    "time": last_loc.recorded_at.strftime("%H:%M"),
                    "vehicle": driver.vehicle_number or "",
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
        "agent_payments": [p for p in _get_pending_agent_payments(db)],
        "yandex_maps_apikey": _get_yandex_apikey(),
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
    # Race condition oldini olish — orderga lock olamiz
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").with_for_update().first()
    if not order or order.status != "draft":
        return RedirectResponse(url="/supervisor/agent-orders?error=already_confirmed", status_code=303)

    # Order itemlari uchun batch load (Stock + Product) — N+1 oldini olish
    valid_items = [it for it in order.items if it.product_id and (it.quantity or 0) > 0]
    pairs = [(it.warehouse_id if it.warehouse_id else order.warehouse_id, it.product_id) for it in valid_items]
    pairs = [(w, p) for w, p in pairs if w]
    pids = list({p for _, p in pairs})
    whs = list({w for w, _ in pairs})
    stocks_map = {}
    if pids and whs:
        for s in db.query(Stock).filter(Stock.warehouse_id.in_(whs), Stock.product_id.in_(pids)).all():
            stocks_map[(s.warehouse_id, s.product_id)] = s
    products_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()} if pids else {}

    # Ombor qoldig'ini tekshirish
    shortage = []
    for it in valid_items:
        wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
        if not wh_id:
            continue
        stock = stocks_map.get((wh_id, it.product_id))
        have = float(stock.quantity or 0) if stock else 0
        need = float(it.quantity or 0)
        if have + 1e-6 < need:
            prod = products_map.get(it.product_id)
            name = prod.name if prod else f"#{it.product_id}"
            shortage.append(f"{name} (kerak: {need}, bor: {have})")
    if shortage:
        detail = ", ".join(shortage)
        return RedirectResponse(
            url="/supervisor/agent-orders?error=stock&detail=" + quote(f"Ombor yetmaydi: {detail}"),
            status_code=303,
        )
    # Stock chiqarish (DRY: stock_service.apply_sale_stock_deduction)
    apply_sale_stock_deduction(db, order, current_user, note_prefix="Agent sotuv (supervisor tasdiq)")
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
                status="in_progress",
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
    # Race condition oldini olish
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").with_for_update().first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    # Agar tasdiqlangan bo'lsa — stock qaytarish + yetkazishni ham bekor qilish
    if order.status == "confirmed":
        for it in order.items:
            if not it.product_id or not (it.quantity or 0) > 0:
                continue
            wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
            if not wh_id:
                continue
            create_stock_movement(
                db=db,
                warehouse_id=wh_id,
                product_id=it.product_id,
                quantity_change=+float(it.quantity or 0),
                operation_type="sale_revert",
                document_type="Sale",
                document_id=order.id,
                document_number=order.number,
                user_id=current_user.id if current_user else None,
                note=f"Agent buyurtma bekor (reject): {order.number}",
                created_at=datetime.now(),
            )
        from app.models.database import Delivery as DeliveryModel
        # Confirm `in_progress` qo'yadi, lekin pending ham bo'lishi mumkin (oldingi flow)
        delivery = db.query(DeliveryModel).filter(
            DeliveryModel.order_id == order.id,
            DeliveryModel.status.in_(["pending", "in_progress"]),
        ).first()
        if delivery:
            delivery.status = "cancelled"
    order.status = "cancelled"
    db.commit()
    referer = request.headers.get("referer", "/supervisor/agent-orders")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/supervisor/agent-orders/delete/{order_id}")
async def supervisor_delete_agent_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmasini o'chirish (faqat bekor qilingan yoki draft)."""
    from app.models.database import OrderItem as OI, Delivery as DeliveryModel
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    if order.status == "confirmed":
        return RedirectResponse(
            url="/supervisor/agent-orders?error=confirmed_delete&detail=" + quote("Tasdiqlangan buyurtmani to'g'ridan-to'g'ri o'chirib bo'lmaydi. Avval bekor qiling."),
            status_code=303,
        )
    # Cancelled bo'lsa StockMovement orphan bo'lib qolmasligi uchun tozalash
    if order.status == "cancelled":
        delete_stock_movements_for_document(db, "Sale", order.id)
    # Bog'liq yetkazishlarni o'chirish
    db.query(DeliveryModel).filter(DeliveryModel.order_id == order.id).delete()
    # Order itemlarni o'chirish
    db.query(OI).filter(OI.order_id == order.id).delete()
    # Buyurtmani o'chirish
    db.delete(order)
    db.commit()
    return RedirectResponse(url="/supervisor/agent-orders", status_code=303)


def _get_yandex_apikey():
    try:
        from app.config.maps_config import YANDEX_MAPS_API_KEY
        return YANDEX_MAPS_API_KEY or ""
    except Exception:
        return ""


def _get_pending_agent_payments(db):
    payments = db.query(AgentPayment).filter(AgentPayment.status == "pending").order_by(AgentPayment.id.desc()).limit(20).all()
    for p in payments:
        p._agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first()
    return payments


# ==========================================
# SUPERVISOR: AGENT TO'LOVLARI (INKASSATSIYA)
# ==========================================

@router.get("/supervisor/agent-payments", response_class=HTMLResponse)
async def supervisor_agent_payments(
    request: Request,
    status: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovlari ro'yxati — supervisor tasdiqlash uchun."""
    q = db.query(AgentPayment).order_by(AgentPayment.id.desc())
    if status == "pending":
        q = q.filter(AgentPayment.status == "pending")
    elif status == "confirmed":
        q = q.filter(AgentPayment.status == "confirmed")
    elif status == "cancelled":
        q = q.filter(AgentPayment.status == "cancelled")
    payments = q.limit(QUERY_LIMIT_DEFAULT).all()
    # Agent va partner ma'lumotlarini biriktirish
    for p in payments:
        p._agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first()
    return templates.TemplateResponse("supervisor/agent_payments.html", {
        "request": request,
        "payments": payments,
        "status_filter": status,
        "current_user": current_user,
    })


@router.post("/supervisor/agent-payments/confirm/{payment_id}")
async def supervisor_confirm_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini tasdiqlash — mijoz qarzidan ayirish va kassaga kirim qilish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if ap.status != "pending":
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)

    # 1. Agent to'lovini tasdiqlash
    ap.status = "confirmed"
    ap.confirmed_by = current_user.id
    ap.confirmed_at = datetime.now()

    # 2. Mijoz qarzidan ayirish (balance = qarzdorlik)
    partner = db.query(Partner).filter(Partner.id == ap.partner_id).first()
    if partner:
        partner.balance = float(partner.balance or 0) - float(ap.amount or 0)

    # 3. Tegishli kassaga kirim qilish
    pay_type_map = {"naqd": "naqd", "plastik": "plastik", "perechisleniye": "perechisleniye"}
    cash_type = pay_type_map.get(ap.payment_type, "naqd")
    cash_register = db.query(CashRegister).filter(
        CashRegister.payment_type == cash_type,
        CashRegister.is_active == True,
    ).first()
    # Agar mos kassa topilmasa, birinchi faol kassani olish
    if not cash_register:
        cash_register = db.query(CashRegister).filter(CashRegister.is_active == True).first()

    if cash_register:
        # To'lov hujjati yaratish (Payment)
        last_payment = db.query(Payment).order_by(Payment.id.desc()).first()
        next_num = (last_payment.id + 1) if last_payment else 1
        payment_number = f"AGT-{datetime.now().strftime('%Y%m%d')}-{next_num:04d}"

        payment = Payment(
            number=payment_number,
            date=datetime.now(),
            type="income",
            cash_register_id=cash_register.id,
            partner_id=ap.partner_id,
            amount=float(ap.amount or 0),
            payment_type=ap.payment_type,
            category="agent_collection",
            description=f"Agent inkassatsiya: {partner.name if partner else ''}" + (f" — {ap.notes}" if ap.notes else ""),
            user_id=current_user.id,
            status="confirmed",
        )
        db.add(payment)

    # 4. Buyurtmalar qarzini kamaytirish (FIFO — eng eski buyurtmadan boshlab)
    remaining = float(ap.amount or 0)
    if remaining > 0:
        debt_orders = (
            db.query(Order)
            .filter(Order.partner_id == ap.partner_id, Order.debt > 0, Order.type == "sale")
            .order_by(Order.date.asc())
            .all()
        )
        for order in debt_orders:
            if remaining <= 0:
                break
            order_debt = float(order.debt or 0)
            if order_debt <= 0:
                continue
            pay_this = min(remaining, order_debt)
            order.paid = float(order.paid or 0) + pay_this
            order.debt = order_debt - pay_this
            remaining -= pay_this

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/supervisor/agent-payments/reject/{payment_id}")
async def supervisor_reject_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini rad etish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if ap.status != "pending":
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)
    ap.status = "cancelled"
    ap.confirmed_by = current_user.id
    ap.confirmed_at = datetime.now()
    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/supervisor/agent-payments/revert/{payment_id}")
async def supervisor_revert_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Tasdiqlangan to'lovni bekor qilish — kassadan chiqarish, mijoz qarzini qaytarish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if ap.status != "confirmed":
        return RedirectResponse(url="/supervisor/agent-payments?error=not_confirmed", status_code=303)

    # 1. Mijoz qarzini qaytarish
    partner = db.query(Partner).filter(Partner.id == ap.partner_id).first()
    if partner:
        partner.balance = float(partner.balance or 0) + float(ap.amount or 0)

    # 2. Tegishli Payment ni o'chirish (agar yaratilgan bo'lsa)
    # AGT- raqamli to'lovlarni topish
    payments = db.query(Payment).filter(
        Payment.partner_id == ap.partner_id,
        Payment.amount == float(ap.amount or 0),
        Payment.category == "agent_collection",
    ).all()
    for p in payments:
        db.delete(p)

    # 3. Statusni pending ga qaytarish
    ap.status = "pending"
    ap.confirmed_by = None
    ap.confirmed_at = None
    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/supervisor/agent-payments/delete/{payment_id}")
async def supervisor_delete_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini o'chirish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)

    # Agar tasdiqlangan bo'lsa — avval revert qilish
    if ap.status == "confirmed":
        partner = db.query(Partner).filter(Partner.id == ap.partner_id).first()
        if partner:
            partner.balance = float(partner.balance or 0) + float(ap.amount or 0)
        payments = db.query(Payment).filter(
            Payment.partner_id == ap.partner_id,
            Payment.amount == float(ap.amount or 0),
            Payment.category == "agent_collection",
        ).all()
        for p in payments:
            db.delete(p)

    db.delete(ap)
    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.get("/supervisor/agent-payments/edit/{payment_id}", response_class=HTMLResponse)
async def supervisor_edit_agent_payment_form(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini tahrirlash formasi."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    ap._agent = db.query(Agent).filter(Agent.id == ap.agent_id).first()
    ap._partner = db.query(Partner).filter(Partner.id == ap.partner_id).first()
    return templates.TemplateResponse("supervisor/agent_payment_edit.html", {
        "request": request,
        "current_user": current_user,
        "payment": ap,
        "page_title": f"To'lov tahrirlash #{ap.id}",
    })


@router.post("/supervisor/agent-payments/edit/{payment_id}")
async def supervisor_edit_agent_payment_save(
    request: Request,
    payment_id: int,
    amount: float = Form(None),
    payment_type: str = Form(None),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini saqlash."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)

    if ap.status == "pending":
        # Pending — amount, type, notes tahrirlash mumkin
        if amount is not None and amount > 0:
            ap.amount = amount
        if payment_type in ("naqd", "plastik", "perechisleniye"):
            ap.payment_type = payment_type
        ap.notes = notes
    else:
        # Confirmed/cancelled — faqat notes tahrirlash mumkin
        ap.notes = notes

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


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
