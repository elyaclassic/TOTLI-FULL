"""
API — stats, products, partners, agent/driver login va location (PWA/mobil).
"""
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Form, HTTPException, Request
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
)
from sqlalchemy import func as sa_func
from app.deps import require_auth, get_current_user
from app.utils.notifications import get_unread_count, get_user_notifications, mark_as_read
from app.utils.auth import create_session_token, get_user_from_token, verify_password, hash_password, is_legacy_hash
from app.utils.rate_limit import is_blocked, record_failure, record_success, check_api_rate_limit
from fastapi.responses import JSONResponse as _JSONResponse
from app.logging_config import get_logger

logger = get_logger("api_routes")

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/pwa/config")
async def pwa_config():
    """PWA/mobil ilova uchun API asosiy manzil. Env: PWA_API_BASE_URL (bo'sh bo'lsa brauzer origin ishlatiladi)."""
    return {"apiBaseUrl": os.getenv("PWA_API_BASE_URL", "").strip()}


@router.get("/stats")
async def api_stats(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return _JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return _JSONResponse(status_code=429, content={"error": "Too Many Requests"})
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
        return _JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return _JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    products = db.query(Product).filter(Product.is_active == True).all()
    return [{"id": p.id, "name": p.name, "code": p.code, "price": p.sale_price} for p in products]


@router.get("/partners")
async def api_partners(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return _JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return _JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    partners = db.query(Partner).filter(Partner.is_active == True).all()
    return [{"id": p.id, "name": p.name, "balance": p.balance} for p in partners]


@router.get("/agents/locations")
async def get_agents_locations(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return _JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return _JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    result = []
    for agent in agents:
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            result.append({
                "id": agent.id,
                "name": agent.full_name,
                "code": agent.code,
                "lat": last_loc.latitude,
                "lng": last_loc.longitude,
                "time": last_loc.recorded_at.isoformat(),
                "battery": getattr(last_loc, "battery", None),
            })
    return result


@router.get("/drivers/locations")
async def get_drivers_locations(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return _JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if check_api_rate_limit(request):
        return _JSONResponse(status_code=429, content={"error": "Too Many Requests"})
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    result = []
    for driver in drivers:
        last_loc = (
            db.query(DriverLocation)
            .filter(DriverLocation.driver_id == driver.id)
            .order_by(DriverLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            result.append({
                "id": driver.id,
                "name": driver.full_name,
                "code": driver.code,
                "vehicle": driver.vehicle_number,
                "lat": last_loc.latitude,
                "lng": last_loc.longitude,
                "time": last_loc.recorded_at.isoformat(),
                "speed": getattr(last_loc, "speed", None),
            })
    return result


def _role_dashboard_url(role: str) -> str:
    """Rolga mos dashboard URL. Faqat admin bosh sahifaga; ishlab chiqarish foydalanuvchilari /production/orders da qoladi."""
    role_map = {
        "admin": "/",
        "manager": "/sales",
        "production": "/production/orders",
        "qadoqlash": "/production/orders",
        "rahbar": "/production/orders",
        "raxbar": "/production/orders",
    }
    return role_map.get((role or "").strip().lower(), "/production/orders")


def _normalize_phone(phone: str) -> str:
    """Telefon raqamini normalize qilish (+998901234567 formatiga)"""
    if not phone:
        return ""
    # Faqat raqamlarni va + belgisini qoldiramiz
    normalized = "".join(c for c in phone if c.isdigit() or c == "+")
    
    # Agar + bilan boshlanmasa va 998 bilan boshlansa, + qo'shamiz
    if normalized.startswith("998") and not normalized.startswith("+998"):
        normalized = "+" + normalized
    
    # Agar 9 raqam bilan boshlansa (998 ni tashlab), +998 qo'shamiz
    if len(normalized) == 9 and normalized.isdigit():
        normalized = "+998" + normalized
    
    # Agar 12 raqam bo'lsa va + bilan boshlanmasa, + qo'shamiz
    if len(normalized) == 12 and normalized.isdigit() and normalized.startswith("998"):
        normalized = "+" + normalized
    
    return normalized


def _get_phone_variants(phone: str) -> list:
    """Telefon raqamining barcha mumkin bo'lgan variantlarini qaytaradi"""
    if not phone:
        return []
    
    variants = [phone]
    normalized = _normalize_phone(phone)
    if normalized and normalized != phone:
        variants.append(normalized)
    
    # Raqamlarni ajratib olish
    digits_only = "".join(c for c in phone if c.isdigit())
    if digits_only:
        variants.append(digits_only)
        if digits_only.startswith("998"):
            variants.append(f"+{digits_only}")
        if len(digits_only) == 9:
            variants.append(f"+998{digits_only}")
    
    # Takrorlanishlarni olib tashlash
    return list(set(variants))


@router.post("/login")
async def unified_login(
    request: Request,
    username: str = Form(..., max_length=100),
    password: str = Form(..., max_length=256),
    db: Session = Depends(get_db),
):
    """Birlashtirilgan login: User (admin/manager/production) yoki Agent/Driver"""
    try:
        blocked, remaining = is_blocked(request)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            return {"success": False, "error": f"Juda ko'p muvaffaqiyatsiz urinish. {minutes} daqiqa {seconds} soniyadan so'ng qayta urinib ko'ring."}
        username = username.strip()
        password = password.strip()
        _safe_username = username.replace("\n", "").replace("\r", "")
        logger.info(f"Login attempt: username='{_safe_username}', password_length={len(password)}")
        
        # Telefon raqami bo'lishi mumkin - normalize qilamiz
        # Agar username raqamlar yoki + bilan boshlansa, telefon raqami deb hisoblaymiz
        is_phone = username.replace("+", "").replace("-", "").replace(" ", "").isdigit()
        phone_variants = _get_phone_variants(username) if is_phone else []
        normalized_phone = _normalize_phone(username) if is_phone else None
        
        logger.info(f"Phone detection: is_phone={is_phone}, variants={phone_variants}")
        
        # 1. User jadvalidan qidirish (admin, manager, production)
        # Avval username yoki phone bilan qidirish
        user_filters = [
            (User.username == username),
            (User.phone == username)
        ]
        if normalized_phone and normalized_phone != username:
            user_filters.append(User.phone == normalized_phone)
        
        user = db.query(User).filter(or_(*user_filters)).first()
        
        if user:
            if not user.is_active:
                logger.warning(f"User '{username}' faol emas")
                return {"success": False, "error": f"Foydalanuvchi '{username}' faol emas"}
            if verify_password(password, user.password_hash):
                # SHA256/oddiy matn → bcrypt: login da yangilash
                if is_legacy_hash(user.password_hash):
                    user.password_hash = hash_password(password)
                    db.commit()
                role = (user.role or "").strip() or "user"
                logger.info(f"User login successful: id={user.id}, role={role}, username={user.username}")
                token = create_session_token(user.id, role)
                redirect_type = "web" if role in ["admin", "manager", "production", "qadoqlash"] else "pwa"
                response_data = {
                    "success": True,
                    "role": role,
                    "redirect": redirect_type,
                    "redirect_url": _role_dashboard_url(role),
                    "token": token,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "full_name": (user.full_name or "") or (user.username or ""),
                        "role": role,
                    },
                }
                # PWA uchun user ma'lumotlarini agent/driver formatida ham qaytarish
                if redirect_type == "pwa":
                    response_data["agent"] = {
                        "id": user.id,
                        "code": user.username,
                        "full_name": (user.full_name or "") or user.username,
                        "phone": user.phone or "",
                    }
                record_success(request)
                logger.info(f"User login response: redirect={redirect_type}, role={role}")
                return response_data
            else:
                # Parol noto'g'ri, lekin foydalanuvchi topildi
                record_failure(request)
                logger.warning(f"User '{username}' parol noto'g'ri")
                return {"success": False, "error": "Parol noto'g'ri"}
        
        # 2. Agent jadvalidan qidirish - telefon raqami bilan
        if is_phone and phone_variants:
            # Barcha telefon raqami variantlari bilan qidirish
            # SQLAlchemy da .in_() metodi list qabul qiladi
            agent = db.query(Agent).filter(Agent.phone.in_(phone_variants)).first()
            # Agar topilmasa, har bir variant bilan alohida qidirish
            if not agent:
                for variant in phone_variants:
                    agent = db.query(Agent).filter(Agent.phone == variant).first()
                    if agent:
                        break
        else:
            # Oddiy username bilan qidirish
            agent = db.query(Agent).filter(Agent.phone == username).first()
        
        if agent:
            if not agent.is_active:
                return {"success": False, "error": f"Agent '{username}' faol emas"}
            
            # Parol telefon raqami bo'lishi kerak - turli formatlarni tekshirish
            agent_phone_variants = _get_phone_variants(agent.phone)
            password_variants = _get_phone_variants(password) if password else []
            
            # Debug: telefon raqami variantlarini ko'rsatish
            logger.info(f"Agent found: id={agent.id}, is_active={agent.is_active}")
            
            # Parol tekshiruvi: parol yoki uning variantlari agent telefon raqami yoki uning variantlari bilan mos kelishi kerak
            password_match = (
                password in agent_phone_variants or 
                password == agent.phone or
                any(pv in agent_phone_variants for pv in password_variants) or
                any(apv in password_variants for apv in agent_phone_variants)
            )
            
            if password_match:
                record_success(request)
                logger.info(f"Agent login successful: id={agent.id}, phone={agent.phone}")
                token = create_session_token(agent.id, "agent")
                return {
                    "success": True,
                    "role": "agent",
                    "redirect": "pwa",
                    "token": token,
                    "agent": {
                        "id": agent.id,
                        "code": agent.code,
                        "full_name": agent.full_name,
                        "phone": agent.phone,
                    },
                }
            else:
                record_failure(request)
                logger.warning(f"Agent login failed: password mismatch. Agent id={agent.id}")
                return {"success": False, "error": "Parol noto'g'ri"}
        
        # 3. Driver jadvalidan qidirish - telefon raqami bilan
        if is_phone and phone_variants:
            driver = db.query(Driver).filter(Driver.phone.in_(phone_variants)).first()
            if not driver:
                for variant in phone_variants:
                    driver = db.query(Driver).filter(Driver.phone == variant).first()
                    if driver:
                        break
        else:
            driver = db.query(Driver).filter(Driver.phone == username).first()
        
        if driver:
            if not driver.is_active:
                return {"success": False, "error": f"Haydovchi '{username}' faol emas"}
            
            # Parol telefon raqami bo'lishi kerak - turli formatlarni tekshirish
            driver_phone_variants = _get_phone_variants(driver.phone)
            password_variants = _get_phone_variants(password) if password else []
            
            password_match = (
                password in driver_phone_variants or 
                password == driver.phone or
                any(pv in driver_phone_variants for pv in password_variants) or
                any(dpv in password_variants for dpv in driver_phone_variants)
            )
            
            if password_match:
                record_success(request)
                token = create_session_token(driver.id, "driver")
                return {
                    "success": True,
                    "role": "driver",
                    "redirect": "pwa",
                    "token": token,
                    "driver": {
                        "id": driver.id,
                        "code": driver.code,
                        "full_name": driver.full_name,
                        "phone": driver.phone,
                        "vehicle_number": driver.vehicle_number,
                    },
                }
            else:
                record_failure(request)
                logger.warning(f"Driver login failed: password mismatch. Driver id={driver.id}")
                return {"success": False, "error": "Parol noto'g'ri"}

        record_failure(request)
        logger.warning(f"Login failed: username '{username}' not found in User, Agent, or Driver tables")
        return {"success": False, "error": "Login yoki parol noto'g'ri"}
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"Login error: {error_detail}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/login")
async def agent_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Agent login — User (username+parol) yoki Agent (telefon) orqali"""
    try:
        blocked, remaining = is_blocked(request)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            return {"success": False, "error": f"Juda ko'p muvaffaqiyatsiz urinish. {minutes} daqiqa {seconds} soniyadan so'ng qayta urinib ko'ring."}

        # 1) User jadvalidan qidirish (username + parol)
        user = db.query(User).filter(
            User.username == username.strip(),
            User.is_active == True,
            User.role.in_(["agent", "admin", "manager"]),
        ).first()
        if user and verify_password(password, user.password_hash):
            # User ga bog'langan agent bormi?
            agent = db.query(Agent).filter(Agent.employee_id == user.id, Agent.is_active == True).first()
            if not agent:
                # Agent jadvalida telefon bo'yicha
                if user.phone:
                    agent = db.query(Agent).filter(Agent.phone == user.phone, Agent.is_active == True).first()
            if not agent:
                # Agent avtomatik yaratish (agent roli uchun)
                if user.role == "agent":
                    last_agent = db.query(Agent).order_by(Agent.id.desc()).first()
                    seq = (last_agent.id + 1) if last_agent else 1
                    agent = Agent(
                        code=f"AG{seq:03d}",
                        full_name=user.full_name or user.username,
                        phone=user.phone or "",
                        is_active=True,
                        employee_id=user.id,
                    )
                    db.add(agent)
                    db.commit()
                    db.refresh(agent)
                else:
                    record_failure(request)
                    return {"success": False, "error": "Agent profili topilmadi"}
            record_success(request)
            token = create_session_token(agent.id, "agent")
            return {
                "success": True,
                "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone or ""},
                "token": token,
            }

        # 2) Agent jadvalidan telefon bilan qidirish (eski usul)
        agent = db.query(Agent).filter(Agent.phone == username.strip()).first()
        if agent and agent.is_active and password == agent.phone:
            record_success(request)
            token = create_session_token(agent.id, "agent")
            return {
                "success": True,
                "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone},
                "token": token,
            }

        record_failure(request)
        return {"success": False, "error": "Login yoki parol noto'g'ri"}
    except Exception as e:
        logger.error(f"Agent login error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/driver/login")
async def driver_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        blocked, remaining = is_blocked(request)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            return {"success": False, "error": f"Juda ko'p muvaffaqiyatsiz urinish. {minutes} daqiqa {seconds} soniyadan so'ng qayta urinib ko'ring."}
        driver = db.query(Driver).filter(Driver.phone == username).first()
        if not driver or not driver.is_active:
            record_failure(request)
            return {"success": False, "error": "Haydovchi topilmadi yoki faol emas"}
        if password != driver.phone:
            record_failure(request)
            return {"success": False, "error": "Parol noto'g'ri"}
        record_success(request)
        token = create_session_token(driver.id, "driver")
        return {
            "success": True,
            "driver": {
                "id": driver.id,
                "code": driver.code,
                "full_name": driver.full_name,
                "phone": driver.phone,
                "vehicle_number": driver.vehicle_number,
            },
            "token": token,
        }
    except Exception as e:
        logger.error(f"Driver login error: {e}")
        return {"success": False, "error": "Server xatosi"}


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
async def agent_visits(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent uchun tashriflar ro'yxati"""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Invalid token"}

        visits = (
            db.query(Visit)
            .filter(Visit.agent_id == agent.id)
            .order_by(Visit.visit_date.desc())
            .limit(50)
            .all()
        )
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
        agent_id = user_data.get("user_id")
        if not agent_id:
            return {"success": False, "error": "Invalid token"}
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


def _driver_from_token(token: str, db: Session):
    """Token dan driver olish."""
    if not token:
        return None
    user_data = get_user_from_token(token)
    if not user_data or user_data.get("user_type") != "driver":
        return None
    return db.query(Driver).filter(Driver.id == user_data["user_id"], Driver.is_active == True).first()


@router.get("/driver/deliveries")
async def driver_deliveries(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Haydovchiga tayinlangan yetkazishlar ro'yxati"""
    try:
        tk = token or (request.headers.get("Authorization", "")[7:] if request.headers.get("Authorization", "").startswith("Bearer ") else None)
        driver = _driver_from_token(tk, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        deliveries = (
            db.query(Delivery)
            .filter(Delivery.driver_id == driver.id)
            .order_by(Delivery.created_at.desc())
            .limit(50)
            .all()
        )
        result = []
        for d in deliveries:
            order = db.query(Order).filter(Order.id == d.order_id).first() if d.order_id else None
            partner_name = ""
            if order and order.partner_id:
                p = db.query(Partner).filter(Partner.id == order.partner_id).first()
                partner_name = p.name if p else ""
            result.append({
                "id": d.id,
                "number": d.number,
                "order_number": d.order_number or (order.number if order else ""),
                "delivery_address": d.delivery_address or "",
                "partner_name": partner_name,
                "status": d.status or "pending",
                "planned_date": d.planned_date.isoformat() if d.planned_date else "",
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else "",
                "notes": d.notes or "",
                "total": float(order.total or 0) if order else 0,
            })
        return {"success": True, "deliveries": result}
    except Exception as e:
        logger.error(f"Driver deliveries error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/driver/delivery/{delivery_id}/status")
async def driver_delivery_status(
    delivery_id: int,
    status: str = Form(...),
    latitude: float = Form(None),
    longitude: float = Form(None),
    notes: str = Form(""),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    """Haydovchi yetkazish statusini yangilaydi"""
    try:
        user_data = get_user_from_token(token)
        if not user_data or user_data.get("user_type") != "driver":
            return {"success": False, "error": "Invalid token"}
        driver_id = user_data["user_id"]

        delivery = db.query(Delivery).filter(
            Delivery.id == delivery_id,
            Delivery.driver_id == driver_id,
        ).first()
        if not delivery:
            return {"success": False, "error": "Yetkazish topilmadi"}

        allowed_statuses = ["pending", "picked_up", "in_progress", "delivered", "failed"]
        new_status = (status or "").strip()
        if new_status not in allowed_statuses:
            return {"success": False, "error": "Noto'g'ri status"}

        delivery.status = new_status
        if notes:
            delivery.notes = (delivery.notes or "") + "\n" + notes if delivery.notes else notes

        if new_status == "delivered":
            delivery.delivered_at = datetime.now()
            if latitude:
                delivery.latitude = latitude
            if longitude:
                delivery.longitude = longitude

        db.commit()
        return {"success": True, "status": delivery.status}
    except Exception as e:
        db.rollback()
        logger.error(f"Delivery status update error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/driver/stats")
async def driver_stats(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Haydovchi statistikasi"""
    try:
        tk = token or (request.headers.get("Authorization", "")[7:] if request.headers.get("Authorization", "").startswith("Bearer ") else None)
        driver = _driver_from_token(tk, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        today = datetime.now().date()
        pending = db.query(Delivery).filter(Delivery.driver_id == driver.id, Delivery.status.in_(["pending", "picked_up"])).count()
        in_progress = db.query(Delivery).filter(Delivery.driver_id == driver.id, Delivery.status == "in_progress").count()
        today_delivered = db.query(Delivery).filter(
            Delivery.driver_id == driver.id,
            Delivery.status == "delivered",
            sa_func.date(Delivery.delivered_at) == today,
        ).count()
        total = db.query(Delivery).filter(Delivery.driver_id == driver.id).count()

        return {
            "success": True,
            "driver": {"id": driver.id, "code": driver.code, "full_name": driver.full_name},
            "stats": {
                "pending": pending,
                "in_progress": in_progress,
                "today_delivered": today_delivered,
                "total": total,
            },
        }
    except Exception as e:
        logger.error(f"Driver stats error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/notifications/unread")
async def api_notifications_unread(
    token: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """O'qilmagan bildirishnomalar soni va oxirgisi (cookie yoki ?token= orqali)."""
    user = current_user
    # PWA token orqali (cookie bo'lmasa)
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


@router.post("/driver/location")
async def driver_location_update(
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(None),
    battery: int = Form(None),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user_data = get_user_from_token(token)
        if not user_data or user_data.get("user_type") != "driver":
            return {"success": False, "error": "Invalid token"}
        driver_id = user_data["user_id"]
        location = DriverLocation(
            driver_id=driver_id,
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
    return db.query(Agent).filter(Agent.id == user_data["user_id"], Agent.is_active == True).first()


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
        result = []
        for prod in products:
            unit_name = prod.unit.name if prod.unit else ""
            # ProductPrice dan narx olish (agar mavjud bo'lsa)
            pp = db.query(ProductPrice).filter(ProductPrice.product_id == prod.id).first()
            price = float(pp.sale_price or 0) if pp else float(prod.sale_price or 0)
            # Barcha omborlardan umumiy qoldiq
            total_stock = db.query(sa_func.coalesce(sa_func.sum(Stock.quantity), 0)).filter(Stock.product_id == prod.id).scalar()
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
async def agent_my_orders(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent yaratgan buyurtmalar (ORM)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        orders = (
            db.query(Order)
            .filter(Order.agent_id == agent.id)
            .order_by(Order.id.desc())
            .limit(50)
            .all()
        )
        return {
            "success": True,
            "orders": [
                {
                    "id": o.id,
                    "number": o.number,
                    "date": o.date.strftime("%d.%m.%Y %H:%M") if o.date else "",
                    "partner": o.partner.name if o.partner else "",
                    "total": float(o.total or 0),
                    "paid": float(o.paid or 0),
                    "debt": float(o.debt or 0),
                    "status": o.status,
                    "items_count": len(o.items),
                }
                for o in orders
            ],
        }
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
        total_debt = db.query(sa_func.coalesce(sa_func.sum(Partner.balance), 0)).filter(Partner.agent_id == agent.id, Partner.is_active == True).scalar() or 0
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
            debts_list.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y") if o.date else "",
                "total": float(o.total or 0),
                "paid": float(o.paid or 0),
                "debt": debt_val,
                "status": o.status,
            })

        return {
            "success": True,
            "partner_id": partner_id,
            "partner_name": partner.name,
            "total_debt": total_debt,
            "debts": debts_list,
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
