"""
API — stats, products, partners, agent/driver login va location (PWA/mobil).
"""
import os
from datetime import datetime
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
)
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
    """Eski API - backward compatibility"""
    try:
        blocked, remaining = is_blocked(request)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            return {"success": False, "error": f"Juda ko'p muvaffaqiyatsiz urinish. {minutes} daqiqa {seconds} soniyadan so'ng qayta urinib ko'ring."}
        agent = db.query(Agent).filter(Agent.phone == username).first()
        if not agent or not agent.is_active:
            record_failure(request)
            return {"success": False, "error": "Agent topilmadi yoki faol emas"}
        if password != agent.phone:
            record_failure(request)
            return {"success": False, "error": "Parol noto'g'ri"}
        record_success(request)
        token = create_session_token(agent.id, "agent")
        return {
            "success": True,
            "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone},
            "token": token,
        }
    except Exception as e:
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
async def agent_visits(token: str = None, db: Session = Depends(get_db)):
    """Agent uchun tashriflar ro'yxati"""
    try:
        if not token:
            return {"success": False, "error": "Token talab qilinadi"}
        
        user_data = get_user_from_token(token)
        if not user_data or user_data.get("user_type") != "agent":
            return {"success": False, "error": "Invalid token"}
        
        agent_id = user_data.get("user_id")
        
        # Tashriflar jadvali bo'lmasa, bo'sh ro'yxat qaytaramiz
        # Keyinchalik visits jadvali qo'shilganda, bu yerda query qo'shiladi
        return {
            "success": True,
            "visits": []
        }
    except Exception as e:
        logger.error(f"Agent visits error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/location")
async def agent_location_update(
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(None),
    battery: int = Form(None),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user_data = get_user_from_token(token)
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


@router.get("/agent/products")
async def agent_products(request: Request, token: str = None, search: str = None, db: Session = Depends(get_db)):
    """Mahsulotlar ro'yxati (agent buyurtma uchun)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        q = db.query(Product).filter(Product.is_active == True, Product.type == "product")
        if search:
            q = q.filter(Product.name.ilike(f"%{search}%"))
        products = q.order_by(Product.name).all()
        result = []
        for prod in products:
            unit_name = prod.unit.name if prod.unit else ""
            result.append({
                "id": prod.id,
                "name": prod.name,
                "unit": unit_name,
                "price": float(prod.sale_price or 0),
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
    """Agent yangi buyurtma yaratadi (JSON body)."""
    try:
        import json as _json
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
        # Ombor — birinchi faol ombor
        warehouse = db.query(Warehouse).filter(Warehouse.is_active == True).first()
        if not warehouse:
            return {"success": False, "error": "Ombor topilmadi"}
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
        subtotal = 0.0
        order_items = []
        for it in items:
            prod = db.query(Product).filter(Product.id == int(it["product_id"]), Product.is_active == True).first()
            if not prod:
                continue
            qty = float(it.get("qty", it.get("quantity", 1)))
            price = float(it.get("price", prod.sale_price or 0))
            total_line = qty * price
            subtotal += total_line
            order_items.append(OrderItem(
                product_id=prod.id,
                quantity=qty,
                price=price,
                discount_percent=0,
                total=total_line,
            ))
        if not order_items:
            return {"success": False, "error": "Mahsulot topilmadi"}
        order = Order(
            number=order_number,
            date=today,
            type="sale",
            partner_id=partner.id,
            warehouse_id=warehouse.id,
            user_id=None,
            subtotal=subtotal,
            discount_percent=float(partner.discount_percent or 0),
            discount_amount=0,
            total=subtotal,
            paid=0,
            debt=subtotal,
            status="draft",
            payment_type=payment_type,
            note=f"Agent: {agent.code} — {agent.full_name}" + (f". {note}" if note else ""),
        )
        db.add(order)
        db.flush()
        for oi in order_items:
            oi.order_id = order.id
            db.add(oi)
        # agent_id va source ustunlariga yozish (SQLite raw)
        from sqlalchemy import text as _text
        db.commit()
        try:
            with db.bind.begin() as conn:
                conn.execute(_text("UPDATE orders SET agent_id=:aid, source='agent' WHERE id=:oid"),
                             {"aid": agent.id, "oid": order.id})
        except Exception:
            pass
        # Partner balansini yangilash
        partner.balance = float(partner.balance or 0) + subtotal
        db.commit()
        return {"success": True, "order_id": order.id, "order_number": order_number, "total": subtotal}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_create_order: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/my-orders")
async def agent_my_orders(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent yaratgan buyurtmalar."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        from sqlalchemy import text as _text
        rows = db.execute(
            _text("SELECT id FROM orders WHERE agent_id=:aid ORDER BY id DESC LIMIT 50"),
            {"aid": agent.id}
        ).fetchall()
        order_ids = [r[0] for r in rows]
        orders = db.query(Order).filter(Order.id.in_(order_ids)).order_by(Order.id.desc()).all() if order_ids else []
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
    """Agent bugungi statistika."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        today = datetime.now().date()
        from sqlalchemy import text as _text, func
        partners_count = db.query(Partner).filter(Partner.agent_id == agent.id, Partner.is_active == True).count()
        today_orders = db.execute(
            _text("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE agent_id=:aid AND date(created_at)=:d"),
            {"aid": agent.id, "d": str(today)}
        ).fetchone()
        total_debt = db.query(func.sum(Partner.balance)).filter(Partner.agent_id == agent.id, Partner.is_active == True).scalar() or 0
        return {
            "success": True,
            "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone or "", "region": agent.region or ""},
            "stats": {
                "partners_count": partners_count,
                "today_orders": int(today_orders[0] or 0),
                "today_total": float(today_orders[1] or 0),
                "total_debt": float(total_debt),
            },
        }
    except Exception as e:
        logger.error(f"agent_stats: {e}")
        return {"success": False, "error": "Server xatosi"}
