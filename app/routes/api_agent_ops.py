"""
API — agent mobil ilova (CRUD: orders, partners, visits, products, create order, my orders, stats).

Tier C2 5-bosqich: api_routes.py dan ajratib olindi.
16 endpoint + 2 helper (_agent_from_token, _extract_token), ~870 qator.
"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, func, or_

from app.models.database import (
    get_db,
    Agent,
    AgentLocation,
    Order,
    OrderItem,
    Partner,
    Product,
    ProductPrice,
    Stock,
    Visit,
    Warehouse,
)
from app.utils.auth import get_user_from_token
from app.logging_config import get_logger

logger = get_logger("api_agent_ops")

router = APIRouter(prefix="/api", tags=["api-agent"])


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


