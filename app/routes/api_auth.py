"""
API — autentifikatsiya (login, agent PIN, driver login).

Tier C2 3-bosqich: api_routes.py:60-568 dan ajratib olindi.
4 endpoint + 3 helper, ~510 qator.

Endpoint'lar:
- POST /api/login         — unified_login (User + Agent + Driver birlashtirilgan)
- POST /api/agent/login   — agent_login (3 rejim: User bcrypt, PIN, legacy phone)
- POST /api/agent/set-pin — agent_set_pin (PIN o'rnatish/almashtirish, B3 fix)
- POST /api/driver/login  — driver_login

Helper'lar (private):
- _role_dashboard_url — role asosida dashboard URL
- _normalize_phone — telefon raqamini +998XXXXXXXXX formatiga
- _get_phone_variants — mumkin bo'lgan barcha variantlar
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import get_db, User, Agent, Driver
from app.utils.auth import (
    create_session_token, get_user_from_token, verify_password, hash_password, is_legacy_hash,
    hash_pin, verify_pin, validate_pin_format,
)
from app.utils.rate_limit import (
    is_blocked, record_failure, record_success,
    is_agent_blocked, record_agent_failure, record_agent_success,
)
from app.logging_config import get_logger

logger = get_logger("api_auth")

router = APIRouter(prefix="/api", tags=["api-auth"])


# ==========================================
# Helper funksiyalar
# ==========================================

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

    # Takrorlanishlarni olib tashlash (tartib saqlansin)
    return list(dict.fromkeys(variants))


# ==========================================
# Endpoint'lar
# ==========================================

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
        # Masked username: faqat birinchi 3 belgi + "***"
        _masked = (_safe_username[:3] + "***") if len(_safe_username) > 3 else "***"
        logger.info(f"Login attempt: username_mask='{_masked}'")

        # Telefon raqami bo'lishi mumkin - normalize qilamiz
        is_phone = username.replace("+", "").replace("-", "").replace(" ", "").isdigit()
        phone_variants = _get_phone_variants(username) if is_phone else []
        normalized_phone = _normalize_phone(username) if is_phone else None

        logger.info(f"Phone detection: is_phone={is_phone}, variants_count={len(phone_variants)}")

        # 1. User jadvalidan qidirish (admin, manager, production)
        user_filters = [
            (User.username.ilike(username)),
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
            agent = db.query(Agent).filter(Agent.phone.in_(phone_variants)).first()
            if not agent:
                for variant in phone_variants:
                    agent = db.query(Agent).filter(Agent.phone == variant).first()
                    if agent:
                        break
        else:
            agent = db.query(Agent).filter(Agent.phone == username).first()

        if agent:
            if not agent.is_active:
                return {"success": False, "error": f"Agent '{username}' faol emas"}

            agent_phone_variants = _get_phone_variants(agent.phone)
            password_variants = _get_phone_variants(password) if password else []

            logger.info(f"Agent found: id={agent.id}, is_active={agent.is_active}")

            password_match = (
                password in agent_phone_variants or
                password == agent.phone or
                any(pv in agent_phone_variants for pv in password_variants) or
                any(apv in password_variants for apv in agent_phone_variants)
            )

            if password_match:
                record_success(request)
                logger.info(f"Agent login successful: id={agent.id}, phone={(agent.phone or '')[:4]}***")
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
    """Agent login — User (username+parol) yoki Agent (telefon + PIN/legacy) orqali.

    3 rejim (B3 — K5 fix):
    1. User-based (bcrypt): username = User.username, password = User parol
    2. Agent + PIN (yangi xavfsiz usul): username = Agent.phone, password = PIN
    3. Agent + phone-as-password (LEGACY): pin_hash = NULL bo'lsa, backward compat

    Himoyalar:
    - IP bo'yicha rate limit (is_blocked)
    - Agent identifikator bo'yicha per-account rate limit (is_agent_blocked)
    - Legacy login har safar audit log'ga yoziladi
    """
    identifier = (username or "").strip()
    try:
        # 1) IP bo'yicha blok (umumiy brute-force)
        blocked, remaining = is_blocked(request)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            return {"success": False, "error": f"Juda ko'p muvaffaqiyatsiz urinish. {minutes} daqiqa {seconds} soniyadan so'ng qayta urinib ko'ring."}

        # 2) Per-account blok (agent_identifier bo'yicha)
        agent_blocked, agent_remaining = is_agent_blocked(identifier)
        if agent_blocked:
            minutes = agent_remaining // 60
            return {"success": False, "error": f"Bu akkaunt vaqtinchalik bloklangan. {minutes} daqiqadan so'ng qayta urinib ko'ring."}

        # ========== YO'L 1: User-based login (bcrypt) ==========
        user = db.query(User).filter(
            User.username.ilike(identifier),
            User.is_active == True,
            User.role.in_(["agent", "admin", "manager"]),
        ).first()
        if user and verify_password(password, user.password_hash):
            agent = db.query(Agent).filter(Agent.employee_id == user.id, Agent.is_active == True).first()
            if not agent and user.phone:
                agent = db.query(Agent).filter(Agent.phone == user.phone, Agent.is_active == True).first()
            if not agent:
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
                    record_agent_failure(identifier)
                    return {"success": False, "error": "Agent profili topilmadi"}
            record_success(request)
            record_agent_success(identifier)
            token = create_session_token(agent.id, "agent")
            return {
                "success": True,
                "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone or ""},
                "token": token,
                "pin_set": bool(agent.pin_hash),
            }

        # ========== YO'L 2 va 3: Agent jadvalidan telefon bo'yicha ==========
        agent = db.query(Agent).filter(Agent.phone == identifier, Agent.is_active == True).first()
        if agent:
            # YO'L 2: PIN o'rnatilgan — faqat PIN qabul qilinadi
            if agent.pin_hash:
                if verify_pin(password, agent.pin_hash):
                    record_success(request)
                    record_agent_success(identifier)
                    token = create_session_token(agent.id, "agent")
                    return {
                        "success": True,
                        "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone},
                        "token": token,
                        "pin_set": True,
                    }
                # PIN noto'g'ri — phone-as-password ga tushmaydi (downgrade yo'q)
                record_failure(request)
                record_agent_failure(identifier)
                logger.warning(f"[AGENT_LOGIN] Xato PIN agent={agent.code} phone={identifier[:4]}***")
                return {"success": False, "error": "PIN noto'g'ri"}

            # YO'L 3: LEGACY — pin_hash NULL, phone-as-password qabul qilinadi
            # DEPRECATION: AGENT_LEGACY_LOGIN_DISABLED=1 bo'lsa rad qilinadi.
            if password == agent.phone:
                import os as _os
                if (_os.getenv("AGENT_LEGACY_LOGIN_DISABLED", "0") or "0").strip() in ("1", "true", "yes"):
                    record_failure(request)
                    record_agent_failure(identifier)
                    logger.warning(
                        f"[AGENT_LOGIN_LEGACY_BLOCKED] agent={agent.code} phone={identifier[:4]}*** "
                        f"— legacy phone-login o'chirilgan"
                    )
                    return {"success": False, "error": "Legacy login o'chirilgan. Admin orqali PIN o'rnating."}
                record_success(request)
                record_agent_success(identifier)
                token = create_session_token(agent.id, "agent")
                logger.warning(
                    f"[AGENT_LOGIN_LEGACY] agent={agent.code} phone={identifier[:4]}*** "
                    f"— PIN hali o'rnatilmagan, pin_set=False qaytarildi"
                )
                return {
                    "success": True,
                    "agent": {"id": agent.id, "code": agent.code, "full_name": agent.full_name, "phone": agent.phone},
                    "token": token,
                    "pin_set": False,
                    "message": "Iltimos, xavfsizlik uchun PIN kod o'rnating",
                }

        # Hech qaysi yo'l mos kelmadi
        record_failure(request)
        record_agent_failure(identifier)
        return {"success": False, "error": "Login yoki parol noto'g'ri"}
    except Exception as e:
        logger.error(f"Agent login error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/set-pin")
async def agent_set_pin(
    request: Request,
    token: str = Form(...),
    current_password: str = Form(...),
    new_pin: str = Form(...),
    db: Session = Depends(get_db),
):
    """Agent PIN o'rnatish yoki almashtirish (B3).

    2 holat:
    1. Birinchi marta PIN o'rnatish: pin_hash NULL
       - current_password = agent telefon raqami (legacy) YOKI
       - current_password = User paroli (bcrypt, agar agent.employee_id bo'lsa)
    2. Mavjud PIN ni almashtirish: pin_hash bor
       - current_password = eski PIN

    Himoyalar:
    - IP rate limit (is_blocked)
    - Per-agent rate limit (is_agent_blocked)
    - Token tasdiq (agent_id match)
    - Empty current_password REJECT (bo'sh check bypass emas)
    """
    # 1) IP rate limit
    blocked, remaining = is_blocked(request)
    if blocked:
        minutes = remaining // 60
        return {"success": False, "error": f"Juda ko'p urinish. {minutes} daq keyin qayta urining."}

    # 2) Token tekshirish
    data = get_user_from_token(token)
    if not data or data.get("user_type") != "agent":
        record_failure(request)
        return {"success": False, "error": "Token noto'g'ri"}

    agent_id = data.get("user_id")
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.is_active == True).first()
    if not agent:
        record_failure(request)
        return {"success": False, "error": "Agent topilmadi"}

    # 3) Per-agent rate limit (agent_id orqali)
    rate_key = f"setpin:{agent.id}"
    agent_blocked, agent_remaining = is_agent_blocked(rate_key)
    if agent_blocked:
        minutes = agent_remaining // 60
        return {"success": False, "error": f"Juda ko'p PIN o'rnatish urinish. {minutes} daq keyin qayta urining."}

    # 4) current_password majburiy — bo'sh qabul qilinmaydi
    if not (current_password or "").strip():
        record_failure(request)
        record_agent_failure(rate_key)
        return {"success": False, "error": "Joriy parol kiritilishi shart"}

    # 5) PIN format tekshiruvi
    pin_error = validate_pin_format(new_pin)
    if pin_error:
        return {"success": False, "error": pin_error}

    # 6) Joriy parol/PIN tasdiqlash
    auth_ok = False
    if agent.pin_hash:
        # Mavjud PIN ni almashtirish — eski PIN majburiy
        if verify_pin(current_password, agent.pin_hash):
            auth_ok = True
    else:
        # Birinchi marta — ikki yo'l:
        # a) Telefon raqami (legacy rejim uchun mos)
        if agent.phone and current_password == agent.phone:
            auth_ok = True
        # b) User paroli (agar agent.employee_id bo'lsa, bcrypt)
        elif agent.employee_id:
            user = db.query(User).filter(User.id == agent.employee_id).first()
            if user and verify_password(current_password, user.password_hash):
                auth_ok = True

    if not auth_ok:
        record_failure(request)
        record_agent_failure(rate_key)
        logger.warning(f"[AGENT_PIN_SET] Xato current_password agent={agent.code}")
        return {"success": False, "error": "Joriy parol noto'g'ri"}

    try:
        is_first_time = not agent.pin_hash
        agent.pin_hash = hash_pin(new_pin)
        agent.pin_set_at = datetime.now()
        db.commit()
        # Muvaffaqiyatli — rate limit counterlarni tozalash
        record_success(request)
        record_agent_success(rate_key)
        logger.info(f"[AGENT_PIN_SET] agent={agent.code} first_time={is_first_time}")
        return {"success": True, "message": "PIN muvaffaqiyatli o'rnatildi"}
    except Exception as e:
        db.rollback()
        logger.error(f"Agent set-pin error: {e}")
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
