"""
API — stats, products, partners, agent/driver login va location (PWA/mobil).
"""
import os
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import (
    get_db,
    Order,
    OrderItem,
    Product,
    ProductPrice,
    PriceType,
    Stock,
    Warehouse,
    Partner,
    CashRegister,
    Agent,
    Driver,
    AgentLocation,
    DriverLocation,
    User,
    Visit,
    Delivery,
    Payment,
    AgentTask,
    AgentPayment,
)
from sqlalchemy import func as sa_func
from app.deps import require_auth, get_current_user
from app.utils.notifications import get_unread_count, get_user_notifications, mark_as_read
from app.utils.auth import (
    create_session_token, get_user_from_token, verify_password, hash_password, is_legacy_hash,
    hash_pin, verify_pin, validate_pin_format,
)
from app.utils.rate_limit import (
    is_blocked, record_failure, record_success, check_api_rate_limit,
    is_agent_blocked, record_agent_failure, record_agent_success,
)
from fastapi.responses import JSONResponse as _JSONResponse
from app.services.stock_service import create_stock_movement
from app.logging_config import get_logger

logger = get_logger("api_routes")

router = APIRouter(prefix="/api", tags=["api"])


# --- TIZIM ENDPOINTLARI — app/routes/api_system.py ga ko'chirildi (Tier C2 1-bosqich) ---


# --- DASHBOARD ENDPOINTLARI — app/routes/api_dashboard.py ga ko'chirildi (Tier C2 2-bosqich) ---


# --- AUTH (login/PIN/helpers) — app/routes/api_auth.py ga ko'chirildi (Tier C2 3-bosqich) ---


@router.post("/agent/orders")
async def agent_orders(token: str, db: Session = Depends(get_db)):
    try:
        user_data = get_user_from_token(token)
        if not user_data:
            return {"success": False, "error": "Invalid token"}
        return {"success": True, "orders": []}
    except Exception as e:
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partners")
async def agent_partners(token: str = None, db: Session = Depends(get_db)):
    """Agent uchun mijozlar ro'yxati"""
    try:
        # Token query parameter yoki FormData dan olish
        if not token:
            return {"success": False, "error": "Token talab qilinadi"}
        
        user_data = get_user_from_token(token)
        if not user_data or user_data.get("user_type") != "agent":
            return {"success": False, "error": "Invalid token"}
        
        partners = db.query(Partner).filter(Partner.is_active == True).all()
        return {
            "success": True,
            "partners": [
                {"id": p.id, "name": p.name, "phone": p.phone, "address": p.address or ""}
                for p in partners
            ],
        }
    except Exception as e:
        logger.error(f"Agent partners error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/visits")
async def agent_visits(request: Request, token: str = None, date: str = None, db: Session = Depends(get_db)):
    """Agent uchun tashriflar ro'yxati. date=YYYY-MM-DD bo'lsa shu kunniki qaytaradi."""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Invalid token"}

        from sqlalchemy import func as sqla_func
        q = db.query(Visit).filter(Visit.agent_id == agent.id)
        if date:
            try:
                d = datetime.strptime(date, "%Y-%m-%d").date()
                q = q.filter(sqla_func.date(Visit.visit_date) == d)
            except ValueError:
                pass
        visits = q.order_by(Visit.visit_date.desc()).limit(200).all()
        result = []
        for v in visits:
            partner = db.query(Partner).filter(Partner.id == v.partner_id).first() if v.partner_id else None
            result.append({
                "id": v.id,
                "partner_id": v.partner_id,
                "partner_name": partner.name if partner else "",
                "visit_date": v.visit_date.isoformat() if v.visit_date else "",
                "status": v.status or "planned",
                "latitude": v.latitude,
                "longitude": v.longitude,
                "notes": v.notes or "",
                "order_id": v.order_id,
                "check_in_time": v.check_in_time.isoformat() if v.check_in_time else None,
                "check_out_time": v.check_out_time.isoformat() if v.check_out_time else None,
            })
        return {"success": True, "visits": result}
    except Exception as e:
        logger.error(f"Agent visits error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/visit/checkin")
async def agent_visit_checkin(
    request: Request,
    partner_id: int = Form(...),
    latitude: float = Form(None),
    longitude: float = Form(None),
    notes: str = Form(""),
    token: str = Form(""),
    db: Session = Depends(get_db),
):
    """Agent mijozga tashrif boshlanishi (check-in)"""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Invalid token"}

        # So'nggi 2 daqiqada shu mijozga vizit bormi (duplikat oldini olish)
        two_min_ago = datetime.now() - timedelta(minutes=2)
        recent_dup = db.query(Visit).filter(
            Visit.agent_id == agent.id,
            Visit.partner_id == int(partner_id),
            Visit.check_in_time >= two_min_ago,
        ).first()
        if recent_dup:
            return {"success": True, "visit_id": recent_dup.id}  # Mavjud vizitni qaytarish

        # Yakunlanmagan vizit bormi tekshirish
        existing = db.query(Visit).filter(
            Visit.agent_id == agent.id,
            Visit.check_out_time == None,
        ).first()
        if existing:
            existing.check_out_time = datetime.now()
            db.flush()

        visit = Visit(
            agent_id=agent.id,
            partner_id=int(partner_id),
            visit_date=datetime.now(),
            check_in_time=datetime.now(),
            latitude=latitude,
            longitude=longitude,
            status="visited",
            notes=notes or "",
        )
        db.add(visit)
        db.commit()
        db.refresh(visit)
        return {"success": True, "visit_id": visit.id}
    except Exception as e:
        db.rollback()
        logger.error(f"Agent checkin error: {e}")
        return {"success": False, "error": f"Xatolik: {e}"}


@router.post("/agent/visit/checkout")
async def agent_visit_checkout(
    request: Request,
    visit_id: int = Form(...),
    notes: str = Form(""),
    token: str = Form(""),
    db: Session = Depends(get_db),
):
    """Agent tashrifni tugatishi (check-out)"""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Invalid token"}

        visit = db.query(Visit).filter(Visit.id == int(visit_id), Visit.agent_id == agent.id).first()
        if not visit:
            return {"success": False, "error": "Tashrif topilmadi"}

        visit.check_out_time = datetime.now()
        if notes:
            visit.notes = (visit.notes or "") + "\n" + notes if visit.notes else notes
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        logger.error(f"Agent checkout error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/location")
async def agent_location_update(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(None),
    battery: int = Form(None),
    token: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        tk = _extract_token(request, token)
        user_data = get_user_from_token(tk)
        if not user_data or user_data.get("user_type") != "agent":
            return {"success": False, "error": "Invalid token"}
        user_id = user_data.get("user_id")
        if not user_id:
            return {"success": False, "error": "Invalid token"}
        # user_id dan agents jadvalidagi agent_id ni topish
        agent = db.query(Agent).filter(Agent.user_id == user_id).first()
        agent_id = agent.id if agent else user_id
        location = AgentLocation(
            agent_id=agent_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            battery=battery,
        )
        db.add(location)
        db.commit()
        return {"success": True, "location_id": location.id}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": "Server xatosi"}


# --- DRIVER OPS — app/routes/api_driver_ops.py ga ko'chirildi (Tier C2 4-bosqich) ---


# ==========================================
# AGENT MOBIL ILOVA API
# ==========================================

def _agent_from_token(token: str, db: Session):
    """Token dan agent olish."""
    if not token:
        return None
    user_data = get_user_from_token(token)
    if not user_data or user_data.get("user_type") != "agent":
        return None
    user_id = user_data["user_id"]
    # Avval user_id bo'yicha agents jadvalidan qidirish
    agent = db.query(Agent).filter(Agent.user_id == user_id, Agent.is_active == True).first()
    if not agent:
        # Agar user_id == agent.id bo'lsa (eski token)
        agent = db.query(Agent).filter(Agent.id == user_id, Agent.is_active == True).first()
    return agent


def _extract_token(request: Request, token: str = None) -> str:
    """Query param yoki Authorization header dan token olish."""
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


@router.get("/agent/my-partners")
async def agent_my_partners(request: Request, token: str = None, search: str = None, db: Session = Depends(get_db)):
    """Agent o'z klientlari ro'yxati (qarz, manzil, geolokatsiya)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        q = db.query(Partner).filter(Partner.agent_id == agent.id, Partner.is_active == True)
        if search:
            q = q.filter(or_(Partner.name.ilike(f"%{search}%"), Partner.phone.ilike(f"%{search}%")))
        partners = q.order_by(Partner.name).all()
        return {
            "success": True,
            "partners": [
                {
                    "id": p.id,
                    "name": p.name,
                    "phone": p.phone or "",
                    "address": p.address or "",
                    "balance": float(p.balance or 0),
                    "category": p.category or "",
                    "region": p.region or "",
                    "lat": p.latitude,
                    "lng": p.longitude,
                    "visit_day": p.visit_day,
                }
                for p in partners
            ],
        }
    except Exception as e:
        logger.error(f"agent_my_partners: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}")
async def agent_partner_detail(request: Request, partner_id: int, token: str = None, db: Session = Depends(get_db)):
    """Klient tafsilotlari: info + qarz + oxirgi buyurtmalar."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        p = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id, Partner.is_active == True).first()
        if not p:
            return {"success": False, "error": "Klient topilmadi"}
        orders = (
            db.query(Order)
            .filter(Order.partner_id == p.id, Order.type == "sale")
            .order_by(Order.created_at.desc())
            .limit(10)
            .all()
        )
        return {
            "success": True,
            "partner": {
                "id": p.id,
                "name": p.name,
                "legal_name": p.legal_name or "",
                "phone": p.phone or "",
                "phone2": p.phone2 or "",
                "address": p.address or "",
                "landmark": p.landmark or "",
                "category": p.category or "",
                "region": p.region or "",
                "balance": float(p.balance or 0),
                "credit_limit": float(p.credit_limit or 0),
                "discount_percent": float(p.discount_percent or 0),
                "lat": p.latitude,
                "lng": p.longitude,
                "visit_day": p.visit_day,
                "notes": p.notes or "",
            },
            "orders": [
                {
                    "id": o.id,
                    "number": o.number,
                    "date": o.date.strftime("%d.%m.%Y") if o.date else "",
                    "total": float(o.total or 0),
                    "paid": float(o.paid or 0),
                    "debt": float(o.debt or 0),
                    "status": o.status,
                }
                for o in orders
            ],
        }
    except Exception as e:
        logger.error(f"agent_partner_detail: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/partner/{partner_id}/set-location")
async def agent_partner_set_location(
    request: Request,
    partner_id: int,
    token: str = Form(None),
    db: Session = Depends(get_db),
):
    """Agent mijoz lokatsiyasini GPS orqali o'rnatadi."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        p = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id, Partner.is_active == True).first()
        if not p:
            return {"success": False, "error": "Klient topilmadi"}
        form = await request.form()
        lat = form.get("latitude")
        lng = form.get("longitude")
        if not lat or not lng:
            return {"success": False, "error": "Koordinatalar kiritilmagan"}
        p.latitude = float(lat)
        p.longitude = float(lng)
        db.commit()
        return {"success": True, "message": "Lokatsiya saqlandi"}
    except Exception as e:
        logger.error(f"agent_partner_set_location: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/partner/add")
async def agent_partner_add(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    legal_name: str = Form(""),
    landmark: str = Form(""),
    contact_person: str = Form(""),
    notes: str = Form(""),
    category: str = Form(""),
    region: str = Form(""),
    customer_type: str = Form(""),
    sales_channel: str = Form(""),
    visit_days: str = Form(""),
    inn: str = Form(""),
    account: str = Form(""),
    bank: str = Form(""),
    mfo: str = Form(""),
    oked: str = Form(""),
    pinfl: str = Form(""),
    contract_number: str = Form(""),
    contract_date: str = Form(""),
    latitude: float = Form(None),
    longitude: float = Form(None),
    token: str = Form(""),
    db: Session = Depends(get_db),
):
    """Agent yangi mijoz (partner) qo'shadi — to'liq forma."""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        # Kod generatsiya
        last = db.query(Partner).order_by(Partner.id.desc()).first()
        seq = (last.id + 1) if last else 1
        code = f"P{seq:05d}"
        # Visit day — birinchi tanlangan kunni saqlash
        visit_day_val = None
        if visit_days:
            try:
                visit_day_val = int(visit_days.split(",")[0])
            except (ValueError, IndexError):
                pass
        # Contract date
        contract_date_val = None
        if contract_date:
            try:
                from datetime import datetime as _dt
                contract_date_val = _dt.strptime(contract_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass
        partner = Partner(
            code=code,
            name=name.strip(),
            legal_name=(legal_name or "").strip() or None,
            phone=(phone or "").strip(),
            address=(address or "").strip(),
            landmark=(landmark or "").strip() or None,
            contact_person=(contact_person or "").strip() or None,
            notes=(notes or "").strip() or None,
            category=(category or "").strip() or None,
            region=(region or "").strip() or None,
            customer_type=(customer_type or "").strip() or None,
            sales_channel=(sales_channel or "").strip() or None,
            visit_day=visit_day_val,
            inn=(inn or "").strip() or None,
            account=(account or "").strip() or None,
            bank=(bank or "").strip() or None,
            mfo=(mfo or "").strip() or None,
            oked=(oked or "").strip() or None,
            pinfl=(pinfl or "").strip() or None,
            contract_number=(contract_number or "").strip() or None,
            contract_date=contract_date_val,
            latitude=latitude,
            longitude=longitude,
            agent_id=agent.id,
            is_active=True,
            type="customer",
        )
        db.add(partner)
        db.commit()
        db.refresh(partner)
        return {"success": True, "partner_id": partner.id}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_partner_add: {e}")
        return {"success": False, "error": f"Xatolik: {e}"}


@router.get("/agent/products")
async def agent_products(request: Request, token: str = None, search: str = None, db: Session = Depends(get_db)):
    """Mahsulotlar ro'yxati (agent buyurtma uchun) — stock va ProductPrice bilan."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        q = db.query(Product).filter(Product.is_active == True, Product.type == "tayyor")
        if search:
            q = q.filter(Product.name.ilike(f"%{search}%"))
        products = q.order_by(Product.name).all()
        # Tayyor mahsulot ombori ID ni bir marta topish
        tayyor_wh = db.query(Warehouse).filter(Warehouse.id == 3, Warehouse.is_active == True).first()
        if not tayyor_wh:
            tayyor_wh = db.query(Warehouse).filter(Warehouse.name.ilike("%tayyor%"), Warehouse.is_active == True).first()
        tayyor_wh_id = tayyor_wh.id if tayyor_wh else 3
        result = []
        for prod in products:
            unit_name = prod.unit.name if prod.unit else ""
            # ProductPrice dan narx olish (agar mavjud bo'lsa)
            pp = db.query(ProductPrice).filter(ProductPrice.product_id == prod.id).first()
            price = float(pp.sale_price or 0) if pp else float(prod.sale_price or 0)
            # Faqat Tayyor mahsulot ombori dan qoldiq
            total_stock = db.query(sa_func.coalesce(sa_func.sum(Stock.quantity), 0)).filter(
                Stock.product_id == prod.id, Stock.warehouse_id == tayyor_wh_id
            ).scalar()
            result.append({
                "id": prod.id,
                "name": prod.name,
                "unit": unit_name,
                "price": price,
                "stock": float(total_stock),
            })
        return {"success": True, "products": result}
    except Exception as e:
        logger.error(f"agent_products: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/order/create")
async def agent_create_order(
    request: Request,
    db: Session = Depends(get_db),
):
    """Agent yangi buyurtma yaratadi (JSON body). Draft status — admin tasdiqlaydi."""
    try:
        body = await request.json()
        tok = _extract_token(request, body.get("token"))
        agent = _agent_from_token(tok, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        partner_id = body.get("partner_id")
        payment_type = body.get("payment_type", "naqd")
        note = body.get("note", "")
        items = body.get("items", [])
        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}
        if not items:
            return {"success": False, "error": "Mahsulot tanlang"}
        # Ombor — Tayyor mahsulot ombori
        warehouse = db.query(Warehouse).filter(Warehouse.id == 3, Warehouse.is_active == True).first()
        if not warehouse:
            warehouse = db.query(Warehouse).filter(Warehouse.name.ilike("%tayyor%"), Warehouse.is_active == True).first()
        if not warehouse:
            warehouse = db.query(Warehouse).filter(Warehouse.is_active == True).first()
        if not warehouse:
            return {"success": False, "error": "Ombor topilmadi"}
        # Buyurtma raqami: AGT-YYYYMMDD-NNN
        today = datetime.now()
        prefix = f"AGT-{today.strftime('%Y%m%d')}"
        last = db.query(Order).filter(Order.number.like(f"{prefix}%")).order_by(Order.id.desc()).first()
        if last and last.number:
            try:
                seq = int(last.number.split("-")[-1]) + 1
            except Exception:
                seq = 1
        else:
            seq = 1
        order_number = f"{prefix}-{seq:03d}"
        # Partner chegirmasi
        partner_discount = float(partner.discount_percent or 0)
        subtotal = 0.0
        order_items = []
        for it in items:
            prod = db.query(Product).filter(Product.id == int(it["product_id"]), Product.is_active == True).first()
            if not prod:
                continue
            qty = float(it.get("qty", it.get("quantity", 1)))
            # ProductPrice dan narx olish, fallback: Product.sale_price
            pp = db.query(ProductPrice).filter(ProductPrice.product_id == prod.id).first()
            price = float(pp.sale_price or 0) if pp else float(prod.sale_price or 0)
            total_line = qty * price
            subtotal += total_line
            order_items.append(OrderItem(
                product_id=prod.id,
                quantity=qty,
                price=price,
                discount_percent=partner_discount,
                total=total_line * (1 - partner_discount / 100),
            ))
        if not order_items:
            return {"success": False, "error": "Mahsulot topilmadi"}

        # BIRLASHTIRISH: shu mijozning bugungi draft buyurtmasi bormi?
        today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
        existing_order = db.query(Order).filter(
            Order.agent_id == agent.id,
            Order.partner_id == partner.id,
            Order.status == "draft",
            Order.source == "agent",
            Order.date >= today_start,
        ).first()

        if existing_order:
            # Mavjud buyurtmaga itemlarni qo'shish
            for new_oi in order_items:
                # Bir xil mahsulot bormi?
                found = False
                for ex_oi in existing_order.items:
                    if ex_oi.product_id == new_oi.product_id:
                        ex_oi.quantity = float(ex_oi.quantity or 0) + float(new_oi.quantity or 0)
                        ex_oi.total = ex_oi.quantity * float(ex_oi.price or 0) * (1 - float(ex_oi.discount_percent or 0) / 100)
                        found = True
                        break
                if not found:
                    new_oi.order_id = existing_order.id
                    db.add(new_oi)
            # Total qayta hisoblash
            db.flush()
            new_subtotal = sum(float(oi.quantity or 0) * float(oi.price or 0) for oi in existing_order.items)
            new_discount = new_subtotal * float(existing_order.discount_percent or 0) / 100
            new_total = new_subtotal - new_discount
            existing_order.subtotal = new_subtotal
            existing_order.discount_amount = new_discount
            existing_order.total = new_total
            existing_order.debt = new_total - float(existing_order.paid or 0)
            db.commit()
            logger.info(f"Agent order merged: #{existing_order.number}, +{len(order_items)} items, total={new_total}")
            return {"success": True, "order_id": existing_order.id, "order_number": existing_order.number, "total": new_total}

        # Yangi buyurtma yaratish
        discount_amount = subtotal * partner_discount / 100
        total = subtotal - discount_amount
        order = Order(
            number=order_number,
            date=today,
            type="sale",
            partner_id=partner.id,
            warehouse_id=warehouse.id,
            user_id=None,
            agent_id=agent.id,
            source="agent",
            subtotal=subtotal,
            discount_percent=partner_discount,
            discount_amount=discount_amount,
            total=total,
            paid=0,
            debt=total,
            status="draft",
            payment_type=payment_type,
            note=f"Agent: {agent.code} — {agent.full_name}" + (f". {note}" if note else ""),
        )
        db.add(order)
        db.flush()
        for oi in order_items:
            oi.order_id = order.id
            db.add(oi)
        # Draft — partner balance o'zgartirMAYMIZ (faqat tasdiqlangandan keyin)
        db.commit()
        logger.info(f"Agent order created: #{order_number}, agent={agent.code}, partner={partner.name}, total={total}")
        return {"success": True, "order_id": order.id, "order_number": order_number, "total": total}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_create_order: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/my-orders")
async def agent_my_orders(request: Request, token: str = None, date: str = None, db: Session = Depends(get_db)):
    """Agent yaratgan buyurtmalar (ORM). date=YYYY-MM-DD bo'lsa shu kunniki."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        from sqlalchemy import func as sqla_func
        q = db.query(Order).filter(Order.agent_id == agent.id)
        if date:
            try:
                d = datetime.strptime(date, "%Y-%m-%d").date()
                q = q.filter(sqla_func.date(Order.created_at) == d)
            except ValueError:
                pass
        orders = q.order_by(Order.id.desc()).limit(200).all()
        result = []
        for o in orders:
            items = []
            for oi in o.items:
                prod = oi.product
                items.append({
                    "product_id": oi.product_id,
                    "name": prod.name if prod else f"#{oi.product_id}",
                    "quantity": float(oi.quantity or 0),
                    "price": float(oi.price or 0),
                    "total": float(oi.total or 0),
                })
            result.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y %H:%M") if o.date else "",
                "partner_id": o.partner_id,
                "partner": o.partner.name if o.partner else "",
                "partner_name": o.partner.name if o.partner else "",
                "payment_type": o.payment_type or "naqd",
                "total": float(o.total or 0),
                "paid": float(o.paid or 0),
                "debt": float(o.debt or 0),
                "status": o.status,
                "items_count": len(o.items),
                "items": items,
            })
        return {"success": True, "orders": result}
    except Exception as e:
        logger.error(f"agent_my_orders: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/stats")
async def agent_stats(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent bugungi statistika (ORM)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        today = datetime.now().date()
        partners_count = db.query(Partner).filter(Partner.agent_id == agent.id, Partner.is_active == True).count()
        today_orders_q = (
            db.query(sa_func.count(Order.id), sa_func.coalesce(sa_func.sum(Order.total), 0))
            .filter(Order.agent_id == agent.id, sa_func.date(Order.created_at) == today)
            .first()
        )
        today_count = int(today_orders_q[0] or 0)
        today_total = float(today_orders_q[1] or 0)
        # Qarz: agent mijozlaridagi balance + agent buyurtmalaridagi debt
        partner_debt = db.query(sa_func.coalesce(sa_func.sum(Partner.balance), 0)).filter(Partner.agent_id == agent.id, Partner.is_active == True).scalar() or 0
        order_debt = db.query(sa_func.coalesce(sa_func.sum(Order.debt), 0)).filter(Order.agent_id == agent.id, Order.debt > 0).scalar() or 0
        total_debt = max(float(partner_debt), float(order_debt))
        return {
            "success": True,
            "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone or "", "region": agent.region or ""},
            "stats": {
                "partners_count": partners_count,
                "today_orders": today_count,
                "today_total": today_total,
                "total_debt": float(total_debt),
            },
        }
    except Exception as e:
        logger.error(f"agent_stats: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/debtors")
async def agent_debtors(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent mijozlarining qarzdorlar ro'yxati."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        # Partner bo'yicha qarz summasi (Order.debt > 0)
        from sqlalchemy import desc
        results = (
            db.query(Partner.id, Partner.name, Partner.phone, sa_func.sum(Order.debt).label("total_debt"))
            .join(Order, Order.partner_id == Partner.id)
            .filter(Partner.agent_id == agent.id, Partner.is_active == True, Order.debt > 0)
            .group_by(Partner.id, Partner.name, Partner.phone)
            .order_by(desc("total_debt"))
            .all()
        )
        debtors = [
            {"id": r[0], "name": r[1], "phone": r[2] or "", "debt": float(r[3] or 0)}
            for r in results
        ]
        return {"success": True, "debtors": debtors, "total": sum(d["debt"] for d in debtors)}
    except Exception as e:
        logger.error(f"agent_debtors: {e}")
        return {"success": False, "error": "Server xatosi"}


# ==========================================
# SD AGENT API — BATCH, DEBTS, SUMMARY, RECONCILIATION, KPI, TASKS
# ==========================================

@router.post("/agent/order/create-batch")
async def agent_create_order_batch(
    request: Request,
    db: Session = Depends(get_db),
):
    """Bir nechta buyurtmani bir yo'la yaratish (JSON array). Har biri agent_create_order mantiqida."""
    try:
        body = await request.json()
        tok = _extract_token(request, body.get("token") if isinstance(body, dict) else None)
        # Body dict bo'lsa, orders kaliti bilan; yoki to'g'ridan-to'g'ri list
        if isinstance(body, dict):
            tok = tok or _extract_token(request, None)
            orders_data = body.get("orders", [])
        elif isinstance(body, list):
            orders_data = body
        else:
            return {"success": False, "error": "JSON array yoki {orders: [...]} kutilmoqda"}

        agent = _agent_from_token(tok, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        if not orders_data:
            return {"success": False, "error": "Buyurtmalar ro'yxati bo'sh"}

        results = []
        for idx, order_data in enumerate(orders_data):
            try:
                partner_id = order_data.get("partner_id")
                payment_type = order_data.get("payment_type", "naqd")
                note = order_data.get("note", "")
                items = order_data.get("items", [])

                partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
                if not partner:
                    results.append({"index": idx, "success": False, "error": "Klient topilmadi"})
                    continue
                if not items:
                    results.append({"index": idx, "success": False, "error": "Mahsulot tanlang"})
                    continue

                # Ombor
                warehouse = db.query(Warehouse).filter(Warehouse.id == 3, Warehouse.is_active == True).first()
                if not warehouse:
                    warehouse = db.query(Warehouse).filter(Warehouse.name.ilike("%tayyor%"), Warehouse.is_active == True).first()
                if not warehouse:
                    warehouse = db.query(Warehouse).filter(Warehouse.is_active == True).first()
                if not warehouse:
                    results.append({"index": idx, "success": False, "error": "Ombor topilmadi"})
                    continue

                # Buyurtma raqami
                today = datetime.now()
                prefix = f"AGT-{today.strftime('%Y%m%d')}"
                last = db.query(Order).filter(Order.number.like(f"{prefix}%")).order_by(Order.id.desc()).first()
                if last and last.number:
                    try:
                        seq = int(last.number.split("-")[-1]) + 1
                    except Exception:
                        seq = 1
                else:
                    seq = 1
                order_number = f"{prefix}-{seq:03d}"

                partner_discount = float(partner.discount_percent or 0)
                subtotal = 0.0
                order_items = []
                for it in items:
                    prod = db.query(Product).filter(Product.id == int(it["product_id"]), Product.is_active == True).first()
                    if not prod:
                        continue
                    qty = float(it.get("qty", it.get("quantity", 1)))
                    pp = db.query(ProductPrice).filter(ProductPrice.product_id == prod.id).first()
                    price = float(pp.sale_price or 0) if pp else float(prod.sale_price or 0)
                    total_line = qty * price
                    subtotal += total_line
                    order_items.append(OrderItem(
                        product_id=prod.id,
                        quantity=qty,
                        price=price,
                        discount_percent=partner_discount,
                        total=total_line * (1 - partner_discount / 100),
                    ))

                if not order_items:
                    results.append({"index": idx, "success": False, "error": "Mahsulot topilmadi"})
                    continue

                discount_amount = subtotal * partner_discount / 100
                total = subtotal - discount_amount
                order = Order(
                    number=order_number,
                    date=today,
                    type="sale",
                    partner_id=partner.id,
                    warehouse_id=warehouse.id,
                    user_id=None,
                    agent_id=agent.id,
                    source="agent",
                    subtotal=subtotal,
                    discount_percent=partner_discount,
                    discount_amount=discount_amount,
                    total=total,
                    paid=0,
                    debt=total,
                    status="draft",
                    payment_type=payment_type,
                    note=f"Agent: {agent.code} — {agent.full_name}" + (f". {note}" if note else ""),
                )
                db.add(order)
                db.flush()
                for oi in order_items:
                    oi.order_id = order.id
                    db.add(oi)
                db.flush()

                results.append({
                    "index": idx,
                    "success": True,
                    "order_id": order.id,
                    "order_number": order_number,
                    "total": total,
                })
            except Exception as item_err:
                results.append({"index": idx, "success": False, "error": str(item_err)})

        db.commit()
        success_count = sum(1 for r in results if r.get("success"))
        logger.info(f"Agent batch orders: agent={agent.code}, total={len(orders_data)}, success={success_count}")
        return {"success": True, "results": results, "total": len(orders_data), "success_count": success_count}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_create_order_batch: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/debts")
async def agent_partner_debts(
    request: Request,
    partner_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Kontragentning to'lanmagan buyurtmalari (qarz > 0)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}

        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.agent_id == agent.id,
                Order.debt > 0,
                Order.type == "sale",
            )
            .order_by(Order.date.desc())
            .all()
        )

        debts_list = []
        total_debt = 0.0
        for o in orders:
            debt_val = float(o.debt or 0)
            total_debt += debt_val
            items_list = []
            for item in (o.items or []):
                items_list.append({
                    "name": item.product.name if item.product else "—",
                    "quantity": float(item.quantity or 0),
                    "price": float(item.price or 0),
                    "total": float(item.total or 0),
                })
            debts_list.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y") if o.date else "",
                "total": float(o.total or 0),
                "paid": float(o.paid or 0),
                "debt": debt_val,
                "status": o.status,
                "items": items_list,
            })

        # To'lov tarixi (agent inkassatsiya + yetkazish to'lovlari)
        payments_list = []
        partner_payments = (
            db.query(Payment)
            .filter(Payment.partner_id == partner_id, Payment.type == "income", Payment.status == "confirmed")
            .order_by(Payment.date.desc())
            .limit(20)
            .all()
        )
        for p in partner_payments:
            payments_list.append({
                "number": p.number or "",
                "date": p.date.strftime("%d.%m.%Y %H:%M") if p.date else "",
                "amount": float(p.amount or 0),
                "payment_type": p.payment_type or "",
                "description": p.description or "",
            })

        return {
            "success": True,
            "partner_id": partner_id,
            "partner_name": partner.name,
            "total_debt": total_debt,
            "debts": debts_list,
            "payments": payments_list,
        }
    except Exception as e:
        logger.error(f"agent_partner_debts: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/reports/summary")
async def agent_reports_summary(
    request: Request,
    token: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    """Agent kunlik/davriy hisobot: buyurtmalar, to'lovlar, kontragentlar bo'yicha."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        today = datetime.now().date()
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else today
        except (ValueError, TypeError):
            d_from = today
        try:
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
        except (ValueError, TypeError):
            d_to = today

        # Davriy buyurtmalar
        orders = (
            db.query(Order)
            .filter(
                Order.agent_id == agent.id,
                sa_func.date(Order.date) >= d_from,
                sa_func.date(Order.date) <= d_to,
            )
            .all()
        )

        orders_count = len(orders)
        total_amount = sum(float(o.total or 0) for o in orders)

        # Payment breakdown
        cash_orders = [o for o in orders if (o.payment_type or "").lower() in ("naqd", "cash")]
        transfer_orders = [o for o in orders if (o.payment_type or "").lower() in ("plastik", "transfer", "card", "perechisleniye")]
        credit_orders = [o for o in orders if float(o.debt or 0) > 0]

        payment_breakdown = {
            "cash": {
                "count": len(cash_orders),
                "total": sum(float(o.total or 0) for o in cash_orders),
            },
            "transfer": {
                "count": len(transfer_orders),
                "total": sum(float(o.total or 0) for o in transfer_orders),
            },
            "credit": {
                "count": len(credit_orders),
                "total": sum(float(o.debt or 0) for o in credit_orders),
            },
        }

        # Partner breakdown — top 10 kontragentlar
        partner_totals = {}
        for o in orders:
            pid = o.partner_id
            if pid not in partner_totals:
                p = db.query(Partner).filter(Partner.id == pid).first()
                partner_totals[pid] = {
                    "partner_id": pid,
                    "partner_name": p.name if p else "Noma'lum",
                    "orders_count": 0,
                    "total": 0.0,
                }
            partner_totals[pid]["orders_count"] += 1
            partner_totals[pid]["total"] += float(o.total or 0)

        top_partners = sorted(partner_totals.values(), key=lambda x: x["total"], reverse=True)[:10]

        return {
            "success": True,
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "orders_count": orders_count,
            "total_amount": total_amount,
            "payment_breakdown": payment_breakdown,
            "top_partners": top_partners,
        }
    except Exception as e:
        logger.error(f"agent_reports_summary: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/reconciliation")
async def agent_partner_reconciliation(
    request: Request,
    partner_id: int,
    token: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    """Kontragent bilan solishtirma akt (harakat tarixi: debet/kredit/saldo)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}

        today = datetime.now().date()
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else (today - timedelta(days=90))
        except (ValueError, TypeError):
            d_from = today - timedelta(days=90)
        try:
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
        except (ValueError, TypeError):
            d_to = today

        # Davrgacha bo'lgan buyurtmalar va to'lovlar — ochilish qoldig'i
        prior_orders_total = (
            db.query(sa_func.coalesce(sa_func.sum(Order.total), 0))
            .filter(
                Order.partner_id == partner_id,
                Order.agent_id == agent.id,
                Order.type == "sale",
                sa_func.date(Order.date) < d_from,
            )
            .scalar()
        ) or 0

        prior_payments_total = (
            db.query(sa_func.coalesce(sa_func.sum(Payment.amount), 0))
            .filter(
                Payment.partner_id == partner_id,
                Payment.type == "income",
                Payment.status != "cancelled",
                sa_func.date(Payment.date) < d_from,
            )
            .scalar()
        ) or 0

        opening_balance = float(prior_orders_total) - float(prior_payments_total)

        # Davrdagi harakatlar
        movements = []

        # Buyurtmalar (debit)
        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.agent_id == agent.id,
                Order.type == "sale",
                sa_func.date(Order.date) >= d_from,
                sa_func.date(Order.date) <= d_to,
            )
            .order_by(Order.date)
            .all()
        )
        for o in orders:
            movements.append({
                "date": o.date.strftime("%d.%m.%Y %H:%M") if o.date else "",
                "sort_date": o.date.isoformat() if o.date else "",
                "description": f"Sotuv #{o.number}",
                "debit": float(o.total or 0),
                "credit": 0.0,
            })

        # To'lovlar (kredit)
        payments = (
            db.query(Payment)
            .filter(
                Payment.partner_id == partner_id,
                Payment.type == "income",
                Payment.status != "cancelled",
                sa_func.date(Payment.date) >= d_from,
                sa_func.date(Payment.date) <= d_to,
            )
            .order_by(Payment.date)
            .all()
        )
        for p in payments:
            movements.append({
                "date": p.date.strftime("%d.%m.%Y %H:%M") if p.date else "",
                "sort_date": p.date.isoformat() if p.date else "",
                "description": f"To'lov #{p.number}" + (f" ({p.payment_type})" if p.payment_type else ""),
                "debit": 0.0,
                "credit": float(p.amount or 0),
            })

        # Sanaga ko'ra tartiblash
        movements.sort(key=lambda x: x.get("sort_date", ""))

        # Balansni hisoblash
        running_balance = opening_balance
        for m in movements:
            running_balance += m["debit"] - m["credit"]
            m["balance"] = round(running_balance, 2)
            del m["sort_date"]

        closing_balance = running_balance

        return {
            "success": True,
            "partner_id": partner_id,
            "partner_name": partner.name,
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "opening_balance": round(opening_balance, 2),
            "closing_balance": round(closing_balance, 2),
            "movements": movements,
        }
    except Exception as e:
        logger.error(f"agent_partner_reconciliation: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/kpi")
async def agent_kpi(
    request: Request,
    token: str = None,
    period: str = "daily",
    db: Session = Depends(get_db),
):
    """Agent KPI ko'rsatkichlari: tashriflar, buyurtmalar, yangi klientlar, o'rtacha summa."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        today = datetime.now().date()
        period = (period or "daily").lower()
        if period == "weekly":
            d_from = today - timedelta(days=today.weekday())  # Dushanba
        elif period == "monthly":
            d_from = today.replace(day=1)
        else:
            d_from = today

        # Tashriflar
        visits_done = (
            db.query(Visit)
            .filter(
                Visit.agent_id == agent.id,
                sa_func.date(Visit.visit_date) >= d_from,
                sa_func.date(Visit.visit_date) <= today,
            )
            .count()
        )

        # Rejalashtirilgan tashriflar — agent kontragentlari soni
        visits_planned = db.query(Partner).filter(Partner.agent_id == agent.id, Partner.is_active == True).count()

        # Buyurtmalar
        orders = (
            db.query(Order)
            .filter(
                Order.agent_id == agent.id,
                sa_func.date(Order.date) >= d_from,
                sa_func.date(Order.date) <= today,
            )
            .all()
        )
        orders_count = len(orders)
        orders_total = sum(float(o.total or 0) for o in orders)
        average_order_value = (orders_total / orders_count) if orders_count > 0 else 0

        # Yangi kontragentlar (ushbu davrda qo'shilganlar)
        new_partners = (
            db.query(Partner)
            .filter(
                Partner.agent_id == agent.id,
                Partner.is_active == True,
                sa_func.date(Partner.created_at) >= d_from,
                sa_func.date(Partner.created_at) <= today,
            )
            .count()
        )

        # Foizlar
        visits_pct = round((visits_done / visits_planned * 100), 1) if visits_planned > 0 else 0

        return {
            "success": True,
            "period": period,
            "date_from": d_from.isoformat(),
            "date_to": today.isoformat(),
            "metrics": {
                "visits_done": visits_done,
                "visits_planned": visits_planned,
                "visits_percent": visits_pct,
                "orders_count": orders_count,
                "orders_total": round(orders_total, 2),
                "average_order_value": round(average_order_value, 2),
                "new_partners": new_partners,
            },
        }
    except Exception as e:
        logger.error(f"agent_kpi: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/tasks")
async def agent_tasks_list(
    request: Request,
    token: str = None,
    status: str = None,
    db: Session = Depends(get_db),
):
    """Agent vazifalari ro'yxati."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        q = db.query(AgentTask).filter(AgentTask.agent_id == agent.id)
        if status:
            q = q.filter(AgentTask.status == status)
        tasks = q.order_by(AgentTask.due_date.asc(), AgentTask.priority.desc()).all()

        result = []
        for t in tasks:
            partner_name = ""
            if t.partner_id:
                p = db.query(Partner).filter(Partner.id == t.partner_id).first()
                partner_name = p.name if p else ""
            result.append({
                "id": t.id,
                "title": t.title,
                "description": t.description or "",
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "status": t.status,
                "priority": t.priority,
                "partner_id": t.partner_id,
                "partner_name": partner_name,
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            })

        return {"success": True, "tasks": result}
    except Exception as e:
        logger.error(f"agent_tasks_list: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/tasks/{task_id}/complete")
async def agent_task_complete(
    request: Request,
    task_id: int,
    token: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Agent vazifani bajarilgan deb belgilaydi."""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        task = db.query(AgentTask).filter(AgentTask.id == task_id, AgentTask.agent_id == agent.id).first()
        if not task:
            return {"success": False, "error": "Vazifa topilmadi"}

        if task.status == "completed":
            return {"success": False, "error": "Vazifa allaqachon bajarilgan"}

        task.status = "completed"
        task.completed_at = datetime.now()
        if notes:
            task.description = (task.description or "") + f"\n[Bajarildi]: {notes}" if task.description else f"[Bajarildi]: {notes}"
        db.commit()

        logger.info(f"Agent task completed: task_id={task_id}, agent={agent.code}")
        return {"success": True, "task_id": task.id, "status": "completed"}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_task_complete: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/completed-orders")
async def agent_partner_completed_orders(
    request: Request,
    partner_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Mijozning completed sotuvlari (vozvrat uchun)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}
        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.type == "sale",
                Order.status == "completed",
            )
            .order_by(Order.date.desc())
            .limit(30)
            .all()
        )
        result = []
        for o in orders:
            items = []
            for it in o.items:
                prod = it.product
                items.append({
                    "product_id": it.product_id,
                    "name": prod.name if prod else f"#{it.product_id}",
                    "quantity": float(it.quantity or 0),
                    "price": float(it.price or 0),
                    "total": float(it.total or 0),
                })
            result.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y") if o.date else "",
                "total": float(o.total or 0),
                "items": items,
            })
        return {"success": True, "orders": result}
    except Exception as e:
        logger.error(f"agent_partner_completed_orders: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/orders")
async def agent_partner_orders(
    request: Request,
    partner_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Mijozning barcha buyurtmalari ro'yxati (agent uchun)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}
        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.type == "sale",
                Order.status.in_(["draft", "confirmed", "completed"]),
            )
            .order_by(Order.id.desc())
            .limit(50)
            .all()
        )
        result = []
        for o in orders:
            # Kim yaratgan
            created_by = ""
            if o.agent_id:
                ag = db.query(Agent).filter(Agent.id == o.agent_id).first()
                created_by = ag.full_name if ag else "Agent"
            elif o.user_id:
                u = db.query(User).filter(User.id == o.user_id).first()
                created_by = u.full_name if u else "Admin"

            items = []
            for it in o.items:
                prod = it.product
                items.append({
                    "product_id": it.product_id,
                    "name": prod.name if prod else f"#{it.product_id}",
                    "quantity": float(it.quantity or 0),
                    "price": float(it.price or 0),
                    "total": float(it.total or 0),
                })

            # 5 daqiqa ichida o'zgartirilishi mumkin
            created_at = o.created_at or o.date
            can_edit = False
            if created_at and o.status == "draft":
                diff = (datetime.now() - created_at).total_seconds()
                can_edit = diff <= 300  # 5 daqiqa

            result.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y %H:%M") if o.date else "",
                "created_by": created_by,
                "total": float(o.total or 0),
                "paid": float(o.paid or 0),
                "debt": float(o.debt or 0),
                "status": o.status,
                "can_edit": can_edit,
                "items": items,
                "payment_type": o.payment_type or "",
            })
        return {"success": True, "orders": result}
    except Exception as e:
        logger.error(f"agent_partner_orders: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/order/{order_id}/update")
async def agent_order_update(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
):
    """Agent buyurtmani tahrirlaydi (5 daqiqa ichida, faqat draft)."""
    try:
        body = await request.json()
        tok = _extract_token(request, body.get("token"))
        agent = _agent_from_token(tok, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        order = db.query(Order).filter(Order.id == order_id, Order.agent_id == agent.id).first()
        if not order:
            return {"success": False, "error": "Buyurtma topilmadi"}

        if order.status != "draft":
            return {"success": False, "error": "Faqat kutilayotgan buyurtmani o'zgartirish mumkin"}

        # Bekor qilish
        new_status = body.get("status")
        if new_status == "cancelled":
            order.status = "cancelled"
            db.commit()
            logger.info(f"Agent order cancelled: order_id={order.id}, agent={agent.code}")
            return {"success": True, "order_id": order.id}

        created_at = order.created_at or order.date
        if created_at:
            diff = (datetime.now() - created_at).total_seconds()
            if diff > 300:
                return {"success": False, "error": "5 daqiqadan ko'p vaqt o'tdi. Faqat admin o'zgartirishi mumkin"}

        items_data = body.get("items", [])
        payment_type = body.get("payment_type")

        if not items_data:
            return {"success": False, "error": "Mahsulotlar bo'sh"}

        # Eski itemlarni o'chirish
        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

        # Yangi itemlar
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        discount_pct = float(partner.discount_percent or 0) if partner else 0

        subtotal = 0
        for it in items_data:
            product_id = int(it.get("product_id", 0))
            qty = float(it.get("qty", 0))
            if product_id <= 0 or qty <= 0:
                continue
            prod = db.query(Product).filter(Product.id == product_id).first()
            if not prod:
                continue
            price = float(prod.sale_price or 0)
            line_total = round(price * qty, 2)
            subtotal += line_total
            db.add(OrderItem(
                order_id=order.id,
                product_id=product_id,
                quantity=qty,
                price=price,
                total=line_total,
            ))

        discount_amount = round(subtotal * discount_pct / 100, 2)
        total = round(subtotal - discount_amount, 2)

        order.subtotal = subtotal
        order.discount_percent = discount_pct
        order.discount_amount = discount_amount
        order.total = total
        order.debt = total
        order.paid = 0
        if payment_type:
            order.payment_type = payment_type

        db.commit()
        logger.info(f"Agent order updated: order_id={order.id}, agent={agent.code}")
        return {"success": True, "order_id": order.id, "total": total}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_order_update: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/return/create")
async def agent_return_create(
    request: Request,
    db: Session = Depends(get_db),
):
    """Agent vozvrat yaratadi. JSON body: {token, order_id, items: [{product_id, qty}]}."""
    try:
        body = await request.json()
        tok = _extract_token(request, body.get("token"))
        agent = _agent_from_token(tok, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        order_id = body.get("order_id")
        items = body.get("items", [])
        if not order_id:
            return {"success": False, "error": "Buyurtma tanlanmadi"}
        if not items:
            return {"success": False, "error": "Mahsulot tanlang"}
        sale = db.query(Order).filter(
            Order.id == int(order_id),
            Order.type == "sale",
            Order.status == "completed",
        ).first()
        if not sale:
            return {"success": False, "error": "Buyurtma topilmadi"}
        # Ombor — vozvrat yoki asl ombor
        sale_wh = db.query(Warehouse).filter(Warehouse.id == sale.warehouse_id).first()
        if sale_wh and "do'kon" in (sale_wh.name or "").lower():
            return_warehouse_id = sale.warehouse_id
        else:
            vozvrat_wh = db.query(Warehouse).filter(
                Warehouse.name.ilike("%vozvrat%"), Warehouse.is_active == True
            ).first()
            return_warehouse_id = vozvrat_wh.id if vozvrat_wh else sale.warehouse_id
        # Raqam generatsiya
        from datetime import date as date_type
        today_start = date_type.today()
        count = db.query(Order).filter(
            Order.type == "return_sale",
            sa_func.date(Order.created_at) == today_start,
        ).count()
        new_number = f"R-{datetime.now().strftime('%Y%m%d')}-{count + 1:04d}"
        # Sotuv itemlari
        sale_items_by_product = {it.product_id: it for it in sale.items}
        return_order = Order(
            number=new_number,
            type="return_sale",
            partner_id=sale.partner_id,
            warehouse_id=return_warehouse_id,
            price_type_id=sale.price_type_id,
            user_id=None,
            agent_id=agent.id,
            source="agent",
            status="completed",
            payment_type=sale.payment_type,
            note=f"Agent vozvrat: {sale.number} (Agent: {agent.code})",
        )
        db.add(return_order)
        db.flush()
        total_return = 0.0
        for it in items:
            pid = int(it["product_id"])
            qty = float(it.get("qty", it.get("quantity", 0)))
            if qty <= 0:
                continue
            sale_item = sale_items_by_product.get(pid)
            if not sale_item:
                continue
            # Sotilgan miqdordan ko'p qaytarish mumkin emas
            if qty > float(sale_item.quantity or 0) + 0.001:
                qty = float(sale_item.quantity or 0)
            price = float(sale_item.price or 0)
            total_row = qty * price
            db.add(OrderItem(
                order_id=return_order.id,
                product_id=pid,
                quantity=qty,
                price=price,
                total=total_row,
            ))
            total_return += total_row
            create_stock_movement(
                db=db,
                warehouse_id=return_warehouse_id,
                product_id=pid,
                quantity_change=+qty,
                operation_type="return_sale",
                document_type="SaleReturn",
                document_id=return_order.id,
                document_number=return_order.number,
                user_id=None,
                note=f"Agent vozvrat: {sale.number} -> {return_order.number}",
                created_at=return_order.date,
            )
        if total_return <= 0:
            db.rollback()
            return {"success": False, "error": "Qaytarish miqdori kiritilmadi"}
        return_order.subtotal = total_return
        return_order.total = total_return
        return_order.paid = total_return
        return_order.debt = 0
        db.commit()
        logger.info(f"Agent return created: {new_number}, agent={agent.code}, sale={sale.number}, total={total_return}")
        return {"success": True, "return_number": new_number, "total": total_return}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_return_create: {e}")
        return {"success": False, "error": "Server xatosi"}


# ==========================================
# AGENT KASSA (inkassatsiya)
# ==========================================

@router.post("/agent/payment/create")
async def agent_payment_create(request: Request, db: Session = Depends(get_db)):
    """Agent mijozdan pul oldi — pending holatda yaratiladi."""
    try:
        body = await request.json()
        agent = _agent_from_token(_extract_token(request, body.get("token")), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        partner_id = int(body.get("partner_id", 0))
        amount = float(body.get("amount", 0))
        payment_type = body.get("payment_type", "naqd")
        notes = body.get("notes", "")

        if partner_id <= 0 or amount <= 0:
            return {"success": False, "error": "Mijoz va summani kiriting"}

        partner = db.query(Partner).filter(Partner.id == partner_id).first()
        if not partner:
            return {"success": False, "error": "Mijoz topilmadi"}

        ap = AgentPayment(
            agent_id=agent.id,
            partner_id=partner_id,
            amount=amount,
            payment_type=payment_type,
            notes=notes,
            status="pending",
        )
        db.add(ap)
        db.commit()
        logger.info(f"Agent payment created: id={ap.id}, agent={agent.code}, partner={partner.name}, amount={amount}")
        return {"success": True, "payment_id": ap.id}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_payment_create: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/payments")
async def agent_payments(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent to'lovlari ro'yxati."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        payments = (
            db.query(AgentPayment)
            .filter(AgentPayment.agent_id == agent.id)
            .order_by(AgentPayment.id.desc())
            .limit(100)
            .all()
        )
        result = []
        for p in payments:
            partner = db.query(Partner).filter(Partner.id == p.partner_id).first()
            result.append({
                "id": p.id,
                "partner_id": p.partner_id,
                "partner_name": partner.name if partner else "",
                "amount": float(p.amount or 0),
                "payment_type": p.payment_type or "naqd",
                "notes": p.notes or "",
                "status": p.status or "pending",
                "created_at": p.created_at.isoformat() if p.created_at else "",
            })
        return {"success": True, "payments": result}
    except Exception as e:
        logger.error(f"agent_payments: {e}")
        return {"success": False, "error": "Server xatosi"}
