"""
Autentifikatsiya — login, logout.
"""
import os
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, User
from app.deps import get_current_user
from app.utils.auth import verify_password, create_session_token, hash_password, is_legacy_hash
from app.utils.rate_limit import is_blocked, record_failure, record_success

router = APIRouter(tags=["auth"])


def _redirect_after_login(user: User) -> str:
    """Rolga qarab login yoki bosh sahifadan keyin qayerga yo'naltirish. Ishlab chiqarish rollari — tezkor ishlab chiqarish oynasiga (/production)."""
    role = (user.role or "").strip().lower()
    if role == "admin":
        return "/"  # Faqat admin bosh sahifani ko'radi
    if role == "manager":
        return "/sales"  # Buyurtmalar / Sotuvlar
    role_home = {
        "agent": "/agent",
        "driver": "/dashboard/agent",
        "production": "/production",
        "qadoqlash": "/production",
        "sotuvchi": "/sales/pos",
        "rahbar": "/production",
        "raxbar": "/production",
        "operator": "/production",
    }
    # Ishlab chiqarishga tegishli rollar — tezkor ishlab chiqarish oynasi (retsept, ombor, miqdor, Boshlash)
    return role_home.get(role, "/production")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: Optional[User] = Depends(get_current_user)):
    if current_user:
        return RedirectResponse(url=_redirect_after_login(current_user), status_code=303)
    err = request.query_params.get("error")
    if err == "please_retry":
        err = "Xatolik yuz berdi. Qayta kirishni urinib ko'ring."
    return templates.TemplateResponse("login.html", {"request": request, "error": err})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(..., max_length=100),
    password: str = Form(..., max_length=256),
    db: Session = Depends(get_db),
):
    try:
        blocked, remaining = is_blocked(request)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": f"Juda ko'p muvaffaqiyatsiz urinish. {minutes} daqiqa {seconds} soniyadan so'ng qayta urinib ko'ring.",
            })
        username = (username or "").strip()
        password = (password or "").strip()
        if not username or not password:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Login va parolni kiriting!",
            })
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.password_hash):
            record_failure(request)
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Login yoki parol noto'g'ri!",
            })
        if not user.is_active:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Sizning hisobingiz faol emas. Administrator bilan bog'laning.",
            })
        # SHA256/oddiy matn → bcrypt: login muvaffaqiyatli bo'lganda yangilash
        if is_legacy_hash(user.password_hash):
            user.password_hash = hash_password(password)
            db.commit()
        record_success(request)
        role = (user.role or "user").strip().lower()
        token = create_session_token(user.id, role)
        use_https = os.getenv("HTTPS", "").lower() in ("1", "true", "yes")
        redirect_url = _redirect_after_login(user)
        # Login ovozi uchun parametr qo'shish
        sep = "&" if "?" in redirect_url else "?"
        redirect_url += sep + "logged_in=1"
        # Agent uchun: session cookie o'rniga Bearer token bilan /agent ga redirect
        if role == "agent":
            from app.models.database import Agent as AgentModel
            from sqlalchemy import or_
            # employee_id yoki phone orqali agent topish
            agent = db.query(AgentModel).filter(
                AgentModel.is_active == True,
                AgentModel.employee_id == user.id,
            ).first()
            if not agent and user.phone:
                agent = db.query(AgentModel).filter(
                    AgentModel.is_active == True,
                    AgentModel.phone == user.phone,
                ).first()
            if not agent:
                agent = db.query(AgentModel).filter(
                    AgentModel.is_active == True,
                    or_(AgentModel.phone == user.username, AgentModel.full_name == user.full_name),
                ).first()
            if not agent:
                # Agent avtomatik yaratish
                last_agent = db.query(AgentModel).order_by(AgentModel.id.desc()).first()
                seq = (last_agent.id + 1) if last_agent else 1
                agent = AgentModel(
                    code=f"AG{seq:03d}",
                    full_name=user.full_name or user.username,
                    phone=user.phone or "",
                    is_active=True,
                    employee_id=user.id,
                )
                db.add(agent)
                db.commit()
                db.refresh(agent)
            agent_token = create_session_token(agent.id, "agent")
            resp = RedirectResponse(url=f"/agent?token={agent_token}", status_code=303)
            resp.set_cookie("session_token", token, path="/", httponly=True, max_age=86400,
                            samesite="lax", secure=use_https)
            return resp
        resp = RedirectResponse(url=redirect_url, status_code=303)
        resp.set_cookie(
            key="session_token",
            value=token,
            path="/",
            httponly=True,
            max_age=86400,
            samesite="strict",
            secure=use_https,
        )
        return resp
    except Exception as e:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Tizimda xatolik yuz berdi. Qayta urinib ko'ring.",
        })


def _do_logout_response():
    """Session cookie o'chiriladi va /login ga yo'naltiriladi."""
    use_https = os.getenv("HTTPS", "").lower() in ("1", "true", "yes")
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("session_token", path="/", samesite="strict", secure=use_https, httponly=True)
    return resp


@router.get("/logout")
async def logout_get():
    return _do_logout_response()


@router.post("/logout")
async def logout_post():
    return _do_logout_response()
