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
from app.utils.auth import verify_password, create_session_token

router = APIRouter(tags=["auth"])


def _redirect_after_login(user: User) -> str:
    """Rolga qarab login yoki bosh sahifadan keyin qayerga yo'naltirish. Ishlab chiqarish rollari — tezkor ishlab chiqarish oynasiga (/production)."""
    role = (user.role or "").strip().lower()
    if role == "admin":
        return "/"  # Faqat admin bosh sahifani ko'radi
    if role == "manager":
        return "/sales"  # Buyurtmalar / Sotuvlar
    role_home = {
        "agent": "/dashboard/agent",
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
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        username = (username or "").strip()
        password = (password or "").strip()
        if not username or not password:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Login va parolni kiriting!",
            })
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.password_hash):
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Login yoki parol noto'g'ri!",
            })
        if not user.is_active:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Sizning hisobingiz faol emas. Administrator bilan bog'laning.",
            })
        token = create_session_token(user.id, user.username)
        use_https = os.getenv("HTTPS", "").lower() in ("1", "true", "yes")
        redirect_url = _redirect_after_login(user)
        resp = RedirectResponse(url=redirect_url, status_code=303)
        resp.set_cookie(
            key="session_token",
            value=token,
            path="/",
            httponly=True,
            max_age=86400,
            samesite="lax",
            secure=use_https,
        )
        return resp
    except Exception as e:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": f"Tizimda xatolik: {str(e)}",
        })


def _do_logout_response():
    """Session cookie o'chiriladi va /login ga yo'naltiriladi."""
    use_https = os.getenv("HTTPS", "").lower() in ("1", "true", "yes")
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("session_token", path="/", samesite="lax", secure=use_https, httponly=True)
    return resp


@router.get("/logout")
async def logout_get():
    return _do_logout_response()


@router.post("/logout")
async def logout_post():
    return _do_logout_response()
