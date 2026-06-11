# TOTLI BI — Copyright (c) 2026 Elyor Uzakbayev <e999922555@gmail.com>. All rights reserved. See LICENSE.
# reload: 2026-04-10 audit watchdog
# --- .env ni eng birinchi yuklash (boshqa importlar undan oldin env o'qiydi) ---
from dotenv import load_dotenv
load_dotenv()

# --- O3 audit fix: Sentry SDK (optional, faqat SENTRY_DSN o'rnatilgan bo'lsa)
# pip install sentry-sdk[fastapi]  (requirements.txt'ga qo'shildi)
# .env: SENTRY_DSN=https://xxx@sentry.io/yyy
import os as _os_init
_sentry_dsn = _os_init.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[FastApiIntegration(), StarletteIntegration()],
            traces_sample_rate=0.0,  # tracing yo'q (5k events/oy free tier saqlash)
            send_default_pii=False,  # foydalanuvchi ma'lumoti yuborilmaydi
            environment=_os_init.environ.get("SENTRY_ENV", "production"),
            release=_os_init.environ.get("SENTRY_RELEASE", ""),
        )
    except ImportError:
        import logging
        logging.getLogger(__name__).warning(
            "SENTRY_DSN bor lekin sentry-sdk o'rnatilmagan. "
            "pip install sentry-sdk[fastapi] yoki SENTRY_DSN olib tashlang."
        )

# --- Importlar ---
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response, JSONResponse
import uvicorn
import os
import traceback
from datetime import datetime
from app.constants import HTML_404, HTML_500
from app.middleware import global_safe_middleware_impl, csrf_middleware_impl, auth_middleware_impl
from app.models.database import init_db, SessionLocal
from app.utils.db_schema import (
    ensure_cash_opening_balance_column,
    ensure_payments_status_column,
    ensure_agents_pin_hash_column,
    ensure_agents_pin_set_at_column,
    ensure_audit_cooldowns_table,
    ensure_product_is_for_agent_column,
    ensure_sales_plans_table,
    ensure_purchase_return_tables,
    ensure_orders_pending_driver_id_column,
    ensure_partners_price_type_id_column,
    ensure_perf_indexes_20260507,
    ensure_employee_advance_payment_id_column,
    ensure_agent_payment_payment_id_column,
)
from app.routes import auth as auth_routes
from app.routes import dashboard as dashboard_routes
from app.routes import home as home_routes
from app.routes import dashboard_v2 as dashboard_v2_routes
from app.routes import agent_v2 as agent_v2_routes
from app.routes import reports as reports_routes
from app.routes import info as info_routes
from app.routes import sales as sales_routes
from app.routes import qoldiqlar as qoldiqlar_routes
from app.routes import finance as finance_routes
from app.routes import products as products_routes
from app.routes import warehouse as warehouse_routes
from app.routes import purchases as purchases_routes
from app.routes import purchase_returns as purchase_returns_routes
from app.routes import partners as partners_routes
from app.routes import employees as employees_routes
from app.routes import employees_dismissals as employees_dismissals_routes
from app.routes import employees_advances as employees_advances_routes
from app.routes import employees_product_purchases as employees_product_purchases_routes
from app.routes import employees_attendance as employees_attendance_routes
from app.routes import employees_salary as employees_salary_routes
from app.routes import employees_employment as employees_employment_routes
from app.routes import employees_changes as employees_changes_routes
from app.routes import production as production_routes
from app.routes import production_convert as production_convert_routes
from app.routes import chat as chat_routes
from app.routes import api_routes
from app.routes import api_system as api_system_routes
from app.routes import api_dashboard as api_dashboard_routes
from app.routes import api_auth as api_auth_routes
from app.routes import api_search as api_search_routes
from app.routes import api_driver_ops as api_driver_ops_routes
from app.routes import api_agent_ops as api_agent_ops_routes
from app.routes import api_agent_advanced as api_agent_advanced_routes
from app.routes import api_ocr as api_ocr_routes
from app.routes import agents_routes
from app.routes import delivery_routes
from app.routes import sales_deliveries as sales_deliveries_routes
from app.routes import admin as admin_routes
from app.routes import admin_sales_plans as admin_sales_plans_routes
from app.routes import audit_routes
# C3 audit cleanup: period_close.py routes admin.py bilan kollizyada → o'chirildi (commit 057c1b0+)

app = FastAPI(title="TOTLI HOLVA", description="Biznes boshqaruv tizimi", version="1.0")

# --- CORS middleware ---
from fastapi.middleware.cors import CORSMiddleware
_cors_origins = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
        max_age=3600,
    )

# P13 audit fix: StaticFiles + Cache-Control max-age 30 kun (bandwidth -80%)
class _CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        try:
            # APK fayllar uchun cache yo'q (yangi versiyalar darhol kelishi uchun)
            if path.endswith((".apk", ".html")):
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        except Exception:
            pass
        return response


app.mount("/static", _CachedStaticFiles(directory="app/static"), name="static")

# Routerlar (auth, dashboard, home, reports, info, sales, qoldiqlar, finance, products)
app.include_router(auth_routes.router)
app.include_router(home_routes.router)
app.include_router(dashboard_v2_routes.router)
app.include_router(agent_v2_routes.router)
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
app.include_router(purchase_returns_routes.router)
app.include_router(partners_routes.router)
app.include_router(employees_routes.router)
app.include_router(employees_dismissals_routes.router)
app.include_router(employees_advances_routes.router)
app.include_router(employees_product_purchases_routes.router)
app.include_router(employees_attendance_routes.router)
app.include_router(employees_salary_routes.router)
app.include_router(employees_employment_routes.router)
app.include_router(employees_changes_routes.router)
app.include_router(production_routes.router)
app.include_router(production_convert_routes.router)
app.include_router(chat_routes.router)
app.include_router(api_routes.router)
app.include_router(api_system_routes.router)
app.include_router(api_dashboard_routes.router)
app.include_router(api_auth_routes.router)
app.include_router(api_search_routes.router)
app.include_router(api_driver_ops_routes.router)
app.include_router(api_agent_ops_routes.router)
app.include_router(api_agent_advanced_routes.router)
app.include_router(api_ocr_routes.router)
app.include_router(agents_routes.router)
app.include_router(delivery_routes.router)
app.include_router(sales_deliveries_routes.router)
app.include_router(admin_routes.router)
app.include_router(admin_sales_plans_routes.router)
app.include_router(audit_routes.router)
# period_close_routes — C3 cleanup, helper -> services/period_service.py


# ==========================================
# 404 – sahifa topilmadi (HTML)
# ==========================================
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return HTMLResponse(content=HTML_404, status_code=404)


# ==========================================
# MIDDLEWARE (impl — app/middleware.py)
# ==========================================
@app.middleware("http")
async def global_safe_middleware(request: Request, call_next):
    return await global_safe_middleware_impl(request, call_next)


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    try:
        return await csrf_middleware_impl(request, call_next)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        tb = traceback.format_exc()
        traceback.print_exc()
        try:
            from app.middleware import _write_error_log
            _write_error_log(tb, "csrf_middleware")
        except Exception:
            pass
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"detail": "CSRF middleware error"})


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        return await auth_middleware_impl(request, call_next)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        tb = traceback.format_exc()
        traceback.print_exc()
        from app.middleware import _write_error_log
        _write_error_log(tb, "auth_middleware")
        path = (getattr(request, "url", None) and getattr(request.url, "path", None)) or getattr(request, "path", None) or "/"
        if path == "/login" or path == "/favicon.ico":
            return JSONResponse(status_code=500, content={"detail": "Server xatosi"})
        accept = (request.headers.get("accept") or "") if getattr(request, "headers", None) else ""
        if "text/html" in accept:
            resp = RedirectResponse(url="/login?error=please_retry", status_code=303)
            try:
                resp.delete_cookie("session_token", path="/")
            except Exception:
                pass
            return resp
        return JSONResponse(status_code=500, content={"detail": "Server xatosi"})


# ==========================================
# Exception handlers
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
    print("[EXCEPTION_HANDLER_500]", repr(exc), flush=True)
    print(tb, flush=True)
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
    # F4: realtime bus uchun asosiy event loop'ni saqlash (sync publish_sync uchun)
    try:
        import asyncio
        from app.services.realtime_bus import bus
        bus.set_loop(asyncio.get_event_loop())
    except Exception as e:
        print("[Startup] realtime_bus loop:", e)
    try:
        from app.models.database import ensure_attendance_advance_tables, ensure_cash_transfer_inkasatsiya, ensure_orders_delivery_columns
        ensure_attendance_advance_tables()
        ensure_cash_transfer_inkasatsiya()
        ensure_orders_delivery_columns()
    except Exception as e:
        print("[Startup] ensure_tables:", e)
    try:
        db = SessionLocal()
        try:
            ensure_cash_opening_balance_column(db)
            ensure_payments_status_column(db)
            ensure_agents_pin_hash_column(db)
            ensure_agents_pin_set_at_column(db)
            ensure_audit_cooldowns_table(db)
            ensure_product_is_for_agent_column(db)
            ensure_sales_plans_table(db)
            ensure_purchase_return_tables(db)
            ensure_orders_pending_driver_id_column(db)
            ensure_partners_price_type_id_column(db)
            ensure_perf_indexes_20260507(db)
            ensure_employee_advance_payment_id_column(db)
            ensure_agent_payment_payment_id_column(db)
        finally:
            db.close()
    except Exception as e:
        print("[Startup] ensure_xxx_column:", e)
    if os.environ.get("TOTLI_ENV") == "dev":
        # DEV/sandbox (8081): scheduler va Telegram botlar O'TKAZIB YUBORILADI.
        # Aks holda 8081 jonli kameralarni double-poll qiladi va bot tokenida
        # 409 getUpdates conflict bo'lib JONLI botni buzadi.
        print("[Startup] DEV rejim (TOTLI_ENV=dev) — scheduler va Telegram botlar o'tkazib yuborildi")
    else:
        try:
            from app.utils.scheduler import start_scheduler
            start_scheduler()
        except Exception as e:
            print("[Startup] Scheduler ishga tushmadi:", e)
        try:
            from app.utils.telegram_bot import start_telegram_bot
            start_telegram_bot()
        except Exception as e:
            print("[Startup] Telegram chat bot ishga tushmadi:", e)
        try:
            from app.bot.main import start_bot
            await start_bot()
        except Exception as e:
            print("[Startup] Telegram hisobot bot ishga tushmadi:", e)
    # Senior/Expert botlar endi ALOHIDA jarayonda (scripts/senior_bots_standalone.py)
    # — server reload/crash ularni o'ldirmasin, watchdog jarayon-tirikligini bilsin.
    # BOTS_IN_PROCESS=1 .env'da bo'lsagina uvicorn ichida ishga tushadi (rollback).
    # AKS HOLDA standalone bilan birga ishlatsa: bir token 2 getUpdates -> 409.
    if os.getenv("BOTS_IN_PROCESS", "0") == "1" and os.environ.get("TOTLI_ENV") != "dev":
        try:
            from app.bot.senior_bot import start_senior_bot
            await start_senior_bot()
        except Exception as e:
            print("[Startup] Senior bot ishga tushmadi:", e)
        try:
            from app.bot.expert_bots import start_expert_bots
            await start_expert_bots()
        except Exception as e:
            print("[Startup] Expert botlar ishga tushmadi:", e)
    else:
        print("[Startup] Senior/Expert botlar standalone rejimda (uvicorn ichida emas)")
    print("TOTLI HOLVA Business System ishga tushdi!")
    _mp = os.path.abspath(__file__)
    print("  main.py:", _mp)
    try:
        for _dir in [os.path.dirname(_mp), os.getcwd()]:
            if _dir:
                with open(os.path.join(_dir, "server_started.txt"), "w", encoding="utf-8") as f:
                    f.write("main.py: %s\ncwd: %s\n" % (_mp, os.getcwd()))
                break
    except Exception:
        pass


if __name__ == "__main__":
    _dev_mode = os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=_dev_mode)

