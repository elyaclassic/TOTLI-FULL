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
from app.utils.auth import (
    create_session_token, get_user_from_token, verify_password, hash_password, is_legacy_hash,
    hash_pin, verify_pin, validate_pin_format,
)
from app.utils.rate_limit import (
    is_blocked, record_failure, record_success, check_api_rate_limit,
    is_agent_blocked, record_agent_failure, record_agent_success,
)
from fastapi.responses import JSONResponse as _JSONResponse
from app.services.stock_service import create_stock_movement
from app.logging_config import get_logger

logger = get_logger("api_routes")

router = APIRouter(prefix="/api", tags=["api"])


# --- TIZIM ENDPOINTLARI — app/routes/api_system.py ga ko'chirildi (Tier C2 1-bosqich) ---


# --- DASHBOARD ENDPOINTLARI — app/routes/api_dashboard.py ga ko'chirildi (Tier C2 2-bosqich) ---


# --- AUTH (login/PIN/helpers) — app/routes/api_auth.py ga ko'chirildi (Tier C2 3-bosqich) ---


# --- AGENT OPS — app/routes/api_agent_ops.py ga ko'chirildi (Tier C2 5-bosqich) ---


# --- AGENT ADVANCED — app/routes/api_agent_advanced.py ga ko'chirildi (Tier C2 6-bosqich - oxirgi) ---
