"""
TOTLI HOLVA — HTTP middleware: global 500, CSRF, Auth.
"""
import os
import traceback
from datetime import datetime
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.requests import Request as StarletteRequest

from app.constants import HTML_500
from app.utils.auth import get_user_from_token, generate_csrf_token, verify_csrf_token
from app.models.database import SessionLocal, User


def _get_path(request: Request) -> str:
    try:
        return (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", None) or "/"
    except Exception:
        return "/"


def _write_error_log(tb: str, prefix: str = "middleware"):
    for _dir in [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]:
        try:
            if _dir:
                with open(os.path.join(_dir, "server_error.log"), "a", encoding="utf-8") as f:
                    f.write("\n--- [%s] %s ---\n%s\n" % (prefix, datetime.now().isoformat(), tb))
                break
        except Exception:
            continue


async def global_safe_middleware_impl(request: Request, call_next):
    """Xatolikda 500 HTML/JSON qaytarish, traceback log ga."""
    try:
        response = await call_next(request)
        try:
            response.headers["X-Server-Source"] = "pwp"
        except Exception:
            pass
        return response
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        tb = traceback.format_exc()
        print("[GLOBAL_SAFE_ERROR]", tb, flush=True)
        _write_error_log(tb, "global_safe")
        path = _get_path(request)
        if path == "/login" or path == "/favicon.ico":
            r = JSONResponse(status_code=500, content={"detail": "Server xatosi"})
        else:
            try:
                accept = getattr(request, "headers", None) and (request.headers.get("accept") or "")
            except Exception:
                accept = ""
            if "text/html" in (accept or ""):
                r = HTMLResponse(content=HTML_500, status_code=500)
            else:
                r = JSONResponse(status_code=500, content={"detail": "Server xatosi"})
        try:
            r.headers["X-Server-Source"] = "pwp"
        except Exception:
            pass
        return r


async def csrf_middleware_impl(request: Request, call_next):
    """CSRF tekshiruvi — POST/PUT/DELETE da token talab qilinadi."""
    from urllib.parse import parse_qs

    path = _get_path(request)
    method = (getattr(request, "method", None) or "GET")
    if not isinstance(method, str):
        method = "GET"
    method = method.upper()

    if method in ("GET", "HEAD", "OPTIONS"):
        token = request.cookies.get("csrf_token")
        if not token:
            token = generate_csrf_token()
        try:
            setattr(request.state, "csrf_token", token)
        except Exception:
            pass
        response = await call_next(request)
        if not request.cookies.get("csrf_token"):
            response.set_cookie("csrf_token", token, path="/", httponly=False, samesite="lax", max_age=86400 * 7)
        return response

    # Himoyalanmaydigan yo'llar (API login, Android/PWA)
    if path in ("/login", "/api/login", "/api/agent/login", "/api/driver/login", "/api/app/version", "/api/pwa/config") or path.startswith("/static"):
        try:
            setattr(request.state, "csrf_token", request.cookies.get("csrf_token") or generate_csrf_token())
        except Exception:
            pass
        return await call_next(request)
    # Agent/Driver mobil ilova API — Bearer token ishlatadi, CSRF shart emas
    if path.startswith("/api/agent/") or path.startswith("/api/driver/"):
        try:
            setattr(request.state, "csrf_token", request.cookies.get("csrf_token") or generate_csrf_token())
        except Exception:
            pass
        return await call_next(request)

    token = request.cookies.get("csrf_token")
    if not token:
        token = generate_csrf_token()
    try:
        setattr(request.state, "csrf_token", token)
    except Exception:
        pass

    received_token = request.headers.get("X-CSRF-Token")
    content_type = request.headers.get("content-type", "")
    if not received_token and "application/x-www-form-urlencoded" in content_type:
        body = await request.body()
        parsed = parse_qs(body.decode("utf-8", errors="replace"))
        received_token = (parsed.get("csrf_token") or [None])[0]
        async def receive():
            return {"type": "http.request", "body": body}
        request = StarletteRequest(request.scope, receive)
        try:
            setattr(request.state, "csrf_token", token)
        except Exception:
            pass
    elif "multipart/form-data" in content_type and not received_token:
        body = await request.body()
        idx = body.find(b'name="csrf_token"')
        if idx != -1:
            start = body.find(b"\r\n\r\n", idx) + 4
            end = body.find(b"\r\n", start)
            if start != 3 and end != -1:
                received_token = body[start:end].decode("utf-8", errors="replace")
        async def receive():
            return {"type": "http.request", "body": body}
        request = StarletteRequest(request.scope, receive)
        try:
            setattr(request.state, "csrf_token", token)
        except Exception:
            pass

    if not verify_csrf_token(received_token, token):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/?error=csrf", status_code=303)
        return JSONResponse(status_code=403, content={"detail": "CSRF token noto'g'ri yoki yo'q"})

    response = await call_next(request)
    if not request.cookies.get("csrf_token"):
        response.set_cookie("csrf_token", token, path="/", httponly=False, samesite="lax", max_age=86400 * 7)
    return response


async def auth_middleware_impl(request: Request, call_next):
    """Session tekshiruvi — cookie bo‘lmasa /login yoki 401."""
    path = _get_path(request)
    method = (getattr(request, "method", None) or "GET").upper() if isinstance(getattr(request, "method", None), str) else "GET"

    if path in ("/login", "/logout", "/favicon.ico", "/ping"):
        return await call_next(request)
    if path.startswith("/static"):
        return await call_next(request)
    if path in ("/api/login", "/api/agent/login", "/api/driver/login"):
        return await call_next(request)
    if (path == "/api/agent/location" or path == "/api/driver/location") and method == "POST":
        return await call_next(request)
    if path in ("/api/agent/orders", "/api/agent/partners"):
        return await call_next(request)
    # Agent mobil ilova — Bearer token orqali o'z autentifikatsiyasini qiladi
    if path == "/agent" or path.startswith("/api/agent/my-") or path.startswith("/api/agent/partner") or path.startswith("/api/agent/product") or path == "/api/agent/order/create" or path.startswith("/api/agent/order/") or path == "/api/agent/stats" or path.startswith("/api/agent/visit") or path == "/api/agent/visits" or path.startswith("/api/agent/return") or path.startswith("/api/agent/kpi") or path.startswith("/api/agent/reports") or path.startswith("/api/agent/tasks"):
        return await call_next(request)
    # Driver mobil ilova — Bearer token orqali autentifikatsiya
    if path.startswith("/api/driver/"):
        return await call_next(request)

    token = request.cookies.get("session_token")
    if not token:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Login talab qilindi"})
        return RedirectResponse(url="/login", status_code=303)
    user_data = get_user_from_token(token)
    if not user_data:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Session muddati tugadi"})
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie("session_token")
        return resp
    # Eski format token: user_id int bo'lishi shart, aks holda qayta login
    raw_uid = user_data.get("user_id")
    if not isinstance(raw_uid, int):
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Session muddati tugadi"})
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie("session_token")
        return resp
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == raw_uid).first()
        if not user or not user.is_active:
            if path.startswith("/api/"):
                return JSONResponse(status_code=401, content={"detail": "Foydalanuvchi faol emas"})
            resp = RedirectResponse(url="/login", status_code=303)
            resp.delete_cookie("session_token")
            return resp
        return await call_next(request)
    finally:
        db.close()
