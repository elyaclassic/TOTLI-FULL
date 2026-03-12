
# --- Importlar (faqat main.py da ishlatiladiganlar) ---

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response, JSONResponse
from datetime import datetime
import uvicorn
import os
import traceback
from app.models.database import init_db, SessionLocal, User
from app.utils.auth import get_user_from_token, generate_csrf_token, verify_csrf_token
from app.utils.db_schema import ensure_cash_opening_balance_column, ensure_payments_status_column
from app.routes import auth as auth_routes
from app.routes import dashboard as dashboard_routes
from app.routes import home as home_routes
from app.routes import reports as reports_routes
from app.routes import info as info_routes
from app.routes import sales as sales_routes
from app.routes import qoldiqlar as qoldiqlar_routes
from app.routes import finance as finance_routes
from app.routes import products as products_routes
from app.routes import warehouse as warehouse_routes
from app.routes import purchases as purchases_routes
from app.routes import partners as partners_routes
from app.routes import employees as employees_routes
from app.routes import production as production_routes
from app.routes import api_routes
from app.routes import agents_routes
from app.routes import delivery_routes
from app.routes import admin as admin_routes

app = FastAPI(title="TOTLI HOLVA", description="Biznes boshqaruv tizimi", version="1.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routerlar (auth, dashboard, home, reports, info, sales, qoldiqlar, finance, products)
app.include_router(auth_routes.router)
app.include_router(home_routes.router)
app.include_router(reports_routes.router)
app.include_router(info_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(sales_routes.router)
app.include_router(qoldiqlar_routes.router)
app.include_router(finance_routes.router)
app.include_router(finance_routes.cash_router)
app.include_router(products_routes.router)
app.include_router(products_routes.product_check_router)
app.include_router(warehouse_routes.router)
app.include_router(warehouse_routes.inventory_router)
app.include_router(purchases_routes.router)
app.include_router(partners_routes.router)
app.include_router(employees_routes.router)
app.include_router(production_routes.router)
app.include_router(api_routes.router)
app.include_router(agents_routes.router)
app.include_router(delivery_routes.router)
app.include_router(admin_routes.router)


# ==========================================
# 404 – sahifa topilmadi (HTML)
# ==========================================
_HTML_404 = """
<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 - Sahifa topilmadi - TOTLI HOLVA</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center justify-content-center min-vh-100">
    <div class="text-center p-5">
        <h1 class="display-1 text-muted">404</h1>
        <h2 class="text-secondary">Sahifa topilmadi</h2>
        <p class="lead text-muted">So'ralgan sahifa mavjud emas yoki ko'chirilgan.</p>
        <a href="/" class="btn btn-success mt-3">Bosh sahifaga</a>
        <a href="/login" class="btn btn-outline-secondary mt-3 ms-2">Kirish</a>
    </div>
</body>
</html>
"""

_HTML_500 = """
<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>500 - Server xatosi - TOTLI HOLVA</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center justify-content-center min-vh-100">
    <div class="text-center p-5">
        <h1 class="display-1 text-danger">500</h1>
        <h2 class="text-secondary">Server xatosi</h2>
        <p class="lead text-muted">Iltimos, keyinroq urinib ko'ring yoki administrator bilan bog'laning.</p>
        <a href="/" class="btn btn-success mt-3">Bosh sahifaga</a>
        <a href="/login" class="btn btn-outline-secondary mt-3 ms-2">Kirish</a>
    </div>
</body>
</html>
"""


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """404 – sahifa topilmadi (HTML)."""
    return HTMLResponse(content=_HTML_404, status_code=404)


# ==========================================
# GLOBAL FALLBACK - istalgan xatoda 500 o'rniga login (HTML)
# ==========================================
@app.middleware("http")
async def global_safe_middleware(request: Request, call_next):
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
        traceback.print_exc()
        for _dir in [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]:
            try:
                if _dir:
                    log_path = os.path.join(_dir, "server_error.log")
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write("\n--- [global_safe] %s ---\n%s\n" % (datetime.now().isoformat(), tb))
                    break
            except Exception:
                continue
        try:
            path = (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", None) or "/"
        except Exception:
            path = "/"
        if path == "/login" or path == "/favicon.ico":
            r = JSONResponse(status_code=500, content={"detail": "Server xatosi"})
        else:
            try:
                accept = getattr(request, "headers", None) and (request.headers.get("accept") or "")
            except Exception:
                accept = ""
            if "text/html" in (accept or ""):
                # 500 sahifasini ko'rsatamiz, session o'chirilmaydi (logout hissi bermaslik)
                r = HTMLResponse(content=_HTML_500, status_code=500)
            else:
                r = JSONResponse(status_code=500, content={"detail": "Server xatosi"})
        try:
            r.headers["X-Server-Source"] = "pwp"
        except Exception:
            pass
        return r


# ==========================================
# CSRF MIDDLEWARE - POST/PUT/DELETE so'rovlarni himoya qilish
# ==========================================
@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    try:
        return await _csrf_middleware_impl(request, call_next)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return await call_next(request)


async def _csrf_middleware_impl(request: Request, call_next):
    from urllib.parse import parse_qs
    from starlette.requests import Request as StarletteRequest

    try:
        path = (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", None) or "/"
    except Exception:
        path = "/"
    method = (getattr(request, "method", None) or "GET")
    if not isinstance(method, str):
        method = "GET"
    method = method.upper()
    # GET, HEAD, OPTIONS da CSRF tekshiruvi yo'q
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

    # Himoyalanmaydigan yo'llar (API login, static, PWA location)
    if path in ("/login", "/api/agent/login", "/api/driver/login") or path.startswith("/static"):
        try:
            setattr(request.state, "csrf_token", request.cookies.get("csrf_token") or generate_csrf_token())
        except Exception:
            pass
        return await call_next(request)

    # Cookie dan yoki yangi token
    token = request.cookies.get("csrf_token")
    if not token:
        token = generate_csrf_token()
    try:
        setattr(request.state, "csrf_token", token)
    except Exception:
        pass

    # POST/PUT/PATCH/DELETE da token tekshirish
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
        # multipart dan csrf_token ni qidirish (name="csrf_token" dan keyingi qiymat)
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
            return RedirectResponse(url=f"/?error=csrf", status_code=303)
        return JSONResponse(status_code=403, content={"detail": "CSRF token noto'g'ri yoki yo'q"})

    response = await call_next(request)
    if not request.cookies.get("csrf_token"):
        response.set_cookie("csrf_token", token, path="/", httponly=False, samesite="lax", max_age=86400 * 7)
    return response


# ==========================================
# AUTH MIDDLEWARE - barcha sahifa va API ni himoyalash
# ==========================================
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        return await _auth_middleware_impl(request, call_next)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        # ExceptionGroup va boshqa BaseException (traceback brauzerga chiqmasin)
        tb = traceback.format_exc()
        traceback.print_exc()
        for _dir in [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]:
            try:
                if _dir:
                    with open(os.path.join(_dir, "server_error.log"), "a", encoding="utf-8") as f:
                        f.write("\n--- [auth_middleware] %s ---\n%s\n" % (datetime.now().isoformat(), tb))
                    break
            except Exception:
                continue
        try:
            path = (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", None) or "/"
        except Exception:
            path = "/"
        if path == "/login" or path == "/favicon.ico":
            return JSONResponse(status_code=500, content={"detail": "Server xatosi"})
        try:
            accept = (request.headers.get("accept") or "") if getattr(request, "headers", None) else ""
        except Exception:
            accept = ""
        if "text/html" in accept:
            resp = RedirectResponse(url="/login?error=please_retry", status_code=303)
            try:
                resp.delete_cookie("session_token", path="/")
            except Exception:
                pass
            return resp
        return JSONResponse(status_code=500, content={"detail": "Server xatosi"})


async def _auth_middleware_impl(request: Request, call_next):
    path = (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", "/") or "/"
    method = (getattr(request, "method", None) or "GET").upper() if isinstance(getattr(request, "method", None), str) else "GET"
    # Login, logout, static, favicon, ping - himoya kerak emas
    if path in ("/login", "/logout", "/favicon.ico", "/ping"):
        return await call_next(request)
    if path.startswith("/static"):
        return await call_next(request)
    # Mobil/PWA agent va haydovchi API (alohida token bilan)
    if path in ("/api/agent/login", "/api/driver/login"):
        return await call_next(request)
    if (path == "/api/agent/location" or path == "/api/driver/location") and method == "POST":
        return await call_next(request)
    if path in ("/api/agent/orders", "/api/agent/partners"):
        return await call_next(request)
    # Session tekshiruvi
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
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_data["user_id"]).first()
        if not user or not user.is_active:
            if path.startswith("/api/"):
                return JSONResponse(status_code=401, content={"detail": "Foydalanuvchi faol emas"})
            resp = RedirectResponse(url="/login", status_code=303)
            resp.delete_cookie("session_token")
            return resp
        return await call_next(request)
    finally:
        db.close()


# ==========================================
# AUTENTIFIKATSIYA — app.routes.auth da
# ==========================================

@app.exception_handler(403)
async def forbidden_handler(request: Request, exc: HTTPException):
    """403 - brauzer so'rovida bosh sahifaga yo'naltirish"""
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/?error=admin_required", status_code=303)
    return JSONResponse(status_code=403, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def debug_500_handler(request: Request, exc: Exception):
    """500 da: brauzer uchun login ga yo'naltirish, traceback konsolda va server_error.log da."""
    tb = traceback.format_exc()
    traceback.print_exc()
    for _dir in [os.path.dirname(os.path.abspath(__file__)), os.getcwd()]:
        try:
            if _dir:
                with open(os.path.join(_dir, "server_error.log"), "a", encoding="utf-8") as f:
                    f.write("\n--- [exception_handler] %s ---\n%s\n" % (datetime.now().isoformat(), tb))
                break
        except Exception:
            continue
    try:
        path = (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", None) or "/"
    except Exception:
        path = "/"
    if path == "/login" or path == "/favicon.ico":
        return JSONResponse(status_code=500, content={"detail": "Server xatosi"})
    try:
        accept = (request.headers.get("accept") or "") if getattr(request, "headers", None) else ""
    except Exception:
        accept = ""
    if "text/html" in accept:
        resp = RedirectResponse(url="/login?error=please_retry", status_code=303)
        try:
            resp.delete_cookie("session_token", path="/")
        except Exception:
            pass
        return resp
    return JSONResponse(status_code=500, content={"detail": "Server xatosi"})


@app.get("/ping", include_in_schema=False)
async def ping():
    """Qaysi main.py ishlayotganini tekshirish (auth kerak emas)."""
    return {"ok": True, "main_py": os.path.abspath(__file__)}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Brauzer uchun favicon (logo) — 404 oldini olish"""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        favicon_path = os.path.join(root, "app", "static", "images", "logo.png")
        if os.path.isfile(favicon_path):
            return FileResponse(os.path.abspath(favicon_path), media_type="image/png")
    except Exception:
        pass
    return Response(status_code=204)


# ==========================================
# SAVDO — app/routes/sales.py da
# ==========================================

# (sales route'lari sales routerga ko'chirildi)

# ==========================================
# ISHLAB CHIQARISH — app/routes/production.py da
# ==========================================
# (production route'lari production routerga ko'chirildi)

@app.on_event("startup")
async def startup():
    """Dastur ishga tushganda"""
    init_db()
    try:
        from app.models.database import ensure_attendance_advance_tables
        ensure_attendance_advance_tables()
    except Exception as e:
        print("[Startup] ensure_attendance_advance_tables:", e)
    try:
        db = SessionLocal()
        try:
            ensure_cash_opening_balance_column(db)
            ensure_payments_status_column(db)
        finally:
            db.close()
    except Exception as e:
        print("[Startup] ensure_cash_opening_balance_column / ensure_payments_status_column:", e)
    try:
        from app.utils.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print("[Startup] Scheduler ishga tushmadi:", e)
    print("TOTLI HOLVA Business System ishga tushdi!")
    _mp = os.path.abspath(__file__)
    print("  main.py:", _mp)
    try:
        for _dir in [os.path.dirname(_mp), os.getcwd(), r"C:\Users\ELYOR\.cursor\worktrees\business_system\pwp"]:
            if _dir:
                with open(os.path.join(_dir, "server_started.txt"), "w", encoding="utf-8") as f:
                    f.write("main.py: %s\ncwd: %s\n" % (_mp, os.getcwd()))
                break
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)

