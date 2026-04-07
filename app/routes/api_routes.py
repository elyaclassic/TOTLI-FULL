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
from app.utils.auth import create_session_token, get_user_from_token, verify_password, hash_password, is_legacy_hash
from app.utils.rate_limit import is_blocked, record_failure, record_success, check_api_rate_limit
from fastapi.responses import JSONResponse as _JSONResponse
from app.services.stock_service import create_stock_movement
from app.logging_config import get_logger

logger = get_logger("api_routes")

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/pwa/config")
async def pwa_config():
    """PWA/mobil ilova uchun API asosiy manzil. Env: PWA_API_BASE_URL (bo'sh bo'lsa brauzer origin ishlatiladi)."""
    return {"apiBaseUrl": os.getenv("PWA_API_BASE_URL", "").strip()}


@router.get("/app/version")
async def app_version():
    """Mobil ilova versiyasi tekshirish. Yangi versiya bo'lsa yangilash taklif qilinadi."""
    return {
        "version": "1.8.3",
        "build": 43,
        "force_update": True,
        "download_url": "/api/app/download",
        "changelog": "Vizitlar va yetkazishlar sana filtri, kunlar bo'yicha ko'rish",
    }


@router.get("/app/download")
async def app_download():
    """APK faylni to'g'ri MIME type bilan yuklash."""
    apk_path = os.path.join("app", "static", "totli-agent.apk")
    if not os.path.exists(apk_path):
        raise HTTPException(status_code=404, detail="APK topilmadi")
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename="totli-agent.apk",
    )


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
                    user_info = {
                        "id": user.id,
                        "code": user.username,
                        "full_name": (user.full_name or "") or user.username,
                        "phone": user.phone or "",
                    }
                    if role == "driver":
                        response_data["driver"] = user_info
                    else:
                        response_data["agent"] = user_info
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


def _driver_from_token(token: str, db: Session):
    """Token dan driver olish."""
    if not token:
        return None
    user_data = get_user_from_token(token)
    if not user_data or user_data.get("user_type") != "driver":
        return None
    user_id = user_data["user_id"]
    # Avval employee_id orqali
    driver = db.query(Driver).filter(Driver.employee_id == user_id, Driver.is_active == True).first()
    if not driver:
        # Agar user_id == driver.id bo'lsa (eski token)
        driver = db.query(Driver).filter(Driver.id == user_id, Driver.is_active == True).first()
    return driver


@router.get("/driver/deliveries")
async def driver_deliveries(request: Request, token: str = None, date: str = None, db: Session = Depends(get_db)):
    """Haydovchiga tayinlangan yetkazishlar ro'yxati. date=YYYY-MM-DD bo'lsa shu kunniki."""
    try:
        tk = token or (request.headers.get("Authorization", "")[7:] if request.headers.get("Authorization", "").startswith("Bearer ") else None)
        driver = _driver_from_token(tk, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        from sqlalchemy import func as sqla_func
        q = db.query(Delivery).filter(Delivery.driver_id == driver.id)
        if date:
            try:
                d = datetime.strptime(date, "%Y-%m-%d").date()
                q = q.filter(sqla_func.date(Delivery.created_at) == d)
            except ValueError:
                pass
        deliveries = q.order_by(Delivery.created_at.desc()).limit(200).all()
        result = []
        for d in deliveries:
            order = db.query(Order).filter(Order.id == d.order_id).first() if d.order_id else None
            partner = None
            if order and order.partner_id:
                partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
            # Buyurtma mahsulotlari
            items = []
            if order:
                from app.models.database import OrderItem, Product
                for oi in order.items:
                    prod = oi.product
                    items.append({
                        "name": prod.name if prod else f"#{oi.product_id}",
                        "quantity": float(oi.quantity or 0),
                        "price": float(oi.price or 0),
                        "total": float(oi.total or 0),
                    })
            # Lokatsiya — delivery da bo'lsa delivery dan, yo'qsa partner dan
            lat = d.latitude
            lng = d.longitude
            if not lat and partner:
                lat = partner.latitude
            if not lng and partner:
                lng = partner.longitude
            result.append({
                "id": d.id,
                "number": d.number,
                "order_number": d.order_number or (order.number if order else ""),
                "delivery_address": d.delivery_address or (partner.address if partner else ""),
                "partner_name": partner.name if partner else "",
                "partner_phone": partner.phone if partner else "",
                "partner_phone2": partner.phone2 if partner and partner.phone2 else "",
                "partner_address": partner.address if partner else "",
                "landmark": partner.landmark if partner else "",
                "status": d.status or "pending",
                "planned_date": d.planned_date.isoformat() if d.planned_date else "",
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else "",
                "notes": d.notes or "",
                "total": float(order.total or 0) if order else 0,
                "paid": float(order.paid or 0) if order else 0,
                "debt": max(float(order.total or 0) - float(order.paid or 0), 0) if order else 0,
                "latitude": lat,
                "longitude": lng,
                "items": items,
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
    items: str = Form(None),
    naqd: float = Form(0),
    plastik: float = Form(0),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    """Haydovchi yetkazish statusini yangilaydi"""
    try:
        driver = _driver_from_token(token, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        delivery = db.query(Delivery).filter(
            Delivery.id == delivery_id,
            Delivery.driver_id == driver.id,
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

        # Haydovchi o'zgartirgan itemlarni yangilash
        if items and delivery.order_id:
            try:
                modified_items = json.loads(items)
                order = db.query(Order).filter(Order.id == delivery.order_id).first()
                if order:
                    for mi in modified_items:
                        item_name = mi.get("name", "")
                        new_qty = float(mi.get("quantity", 0))
                        new_total = float(mi.get("total", 0))
                        for oi in order.items:
                            if oi.product and oi.product.name == item_name:
                                oi.quantity = new_qty
                                oi.total = new_total
                                break
                    order.total = sum(oi.total for oi in order.items)
            except Exception as e:
                logger.warning(f"Items update xatosi: {e}")

        if new_status == "delivered":
            delivery.delivered_at = datetime.now()
            if latitude:
                delivery.latitude = latitude
            if longitude:
                delivery.longitude = longitude

            # To'lovlarni yaratish (naqd va/yoki plastik)
            order = db.query(Order).filter(Order.id == delivery.order_id).first() if delivery.order_id else None
            partner_id = order.partner_id if order else None
            total_paid = (naqd or 0) + (plastik or 0)

            for pay_type, pay_amount in [("naqd", naqd or 0), ("plastik", plastik or 0)]:
                if pay_amount <= 0:
                    continue
                cash_register = db.query(CashRegister).filter(
                    CashRegister.payment_type == pay_type,
                    CashRegister.is_active == True,
                ).first()
                if not cash_register:
                    cash_register = db.query(CashRegister).filter(CashRegister.is_active == True).first()
                if cash_register:
                    last_p = db.query(Payment).order_by(Payment.id.desc()).first()
                    next_num = (last_p.id + 1) if last_p else 1
                    p_number = f"DLV-{datetime.now().strftime('%Y%m%d')}-{next_num:04d}"
                    partner_name = order.partner.name if order and order.partner else ""
                    payment = Payment(
                        number=p_number,
                        date=datetime.now(),
                        type="income",
                        cash_register_id=cash_register.id,
                        partner_id=partner_id,
                        amount=pay_amount,
                        payment_type=pay_type,
                        category="delivery",
                        description=f"Yetkazish to'lovi ({pay_type}): {partner_name}, #{delivery.number or delivery.id}",
                        user_id=driver.user_id if hasattr(driver, 'user_id') else None,
                        status="confirmed",
                    )
                    db.add(payment)

            # Buyurtma qarzini yangilash
            if order and total_paid > 0:
                order.paid = float(order.paid or 0) + total_paid
                order.debt = max(float(order.total or 0) - float(order.paid or 0), 0)

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
        driver = _driver_from_token(token, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}
        location = DriverLocation(
            driver_id=driver.id,
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
