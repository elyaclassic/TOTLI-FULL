"""
Login brute-force himoyasi — IP bo'yicha urinishlar soni chegaralanadi.
"""
import threading
from datetime import datetime, timedelta

# 5 ta muvaffaqiyatsiz urinishdan keyin 15 daqiqa bloklash
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

_lock = threading.Lock()
# { ip: {"count": int, "locked_until": datetime | None} }
_attempts: dict = {}


import os

# Ishonchli proxy IP lari (masalan: "10.0.0.1,10.0.0.2")
_TRUSTED_PROXIES = set(
    ip.strip() for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if ip.strip()
)


def _get_ip(request) -> str:
    """Haqiqiy IP ni olish.
    X-Forwarded-For faqat TRUSTED_PROXY_IPS da ko'rsatilgan proxylardan kelsa ishoniladi.
    """
    client = getattr(request, "client", None)
    real_ip = client.host if client else "unknown"
    if _TRUSTED_PROXIES and real_ip in _TRUSTED_PROXIES:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return real_ip


def _cleanup():
    """Muddati o'tgan yozuvlarni o'chirish (memory leak oldini olish)."""
    now = datetime.now()
    expired = [
        ip for ip, data in _attempts.items()
        if data["locked_until"] is not None and data["locked_until"] < now
        and data["count"] < MAX_ATTEMPTS
    ]
    # Faqat lock muddati o'tgan va count sifirlanishi kerak bo'lganlarni o'chirish
    to_delete = [
        ip for ip, data in _attempts.items()
        if data["locked_until"] is not None and data["locked_until"] < now
    ]
    for ip in to_delete:
        del _attempts[ip]


def is_blocked(request) -> tuple[bool, int]:
    """
    IP bloklangan bo'lsa (True, qolgan_soniyalar) qaytaradi.
    Bloklangmagan bo'lsa (False, 0) qaytaradi.
    """
    ip = _get_ip(request)
    with _lock:
        _cleanup()
        data = _attempts.get(ip)
        if not data:
            return False, 0
        if data["locked_until"] and datetime.now() < data["locked_until"]:
            remaining = int((data["locked_until"] - datetime.now()).total_seconds())
            return True, remaining
        return False, 0


def record_failure(request):
    """Muvaffaqiyatsiz login — urinish qayd etiladi, kerak bo'lsa bloklash."""
    ip = _get_ip(request)
    with _lock:
        data = _attempts.setdefault(ip, {"count": 0, "locked_until": None})
        # Oldingi lock muddati o'tgan bo'lsa — sifirla
        if data["locked_until"] and datetime.now() >= data["locked_until"]:
            data["count"] = 0
            data["locked_until"] = None
        data["count"] += 1
        if data["count"] >= MAX_ATTEMPTS:
            data["locked_until"] = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)


def record_success(request):
    """Muvaffaqiyatli login — IP uchun hisoblagichni sifirla."""
    ip = _get_ip(request)
    with _lock:
        _attempts.pop(ip, None)


# --- Public API rate limiter (daqiqada max 60 so'rov) ---
_api_lock = threading.Lock()
API_RATE_LIMIT = 60          # Daqiqada
API_RATE_WINDOW = 60         # Soniya
# { ip: {"count": int, "window_start": datetime} }
_api_requests: dict = {}


def check_api_rate_limit(request) -> bool:
    """Public API uchun rate limit.
    True qaytarsa — limit oshib ketgan (429 qaytarish kerak).
    """
    ip = _get_ip(request)
    now = datetime.now()
    with _api_lock:
        data = _api_requests.get(ip)
        if not data or (now - data["window_start"]).total_seconds() >= API_RATE_WINDOW:
            _api_requests[ip] = {"count": 1, "window_start": now}
            return False
        data["count"] += 1
        return data["count"] > API_RATE_LIMIT


# --- Agent login: per-account brute-force himoyasi (B3) ---
# IP emas, agent_identifier (phone yoki username) bo'yicha kuzatiladi.
# Bu tarmoqdan chiqib har xil IP'lardan urinishga qarshi himoya.
AGENT_MAX_ATTEMPTS = 5
AGENT_LOCKOUT_MINUTES = 30
_agent_lock = threading.Lock()
# { identifier: {"count": int, "locked_until": datetime | None} }
_agent_attempts: dict = {}


def _agent_cleanup():
    """Muddati o'tgan yozuvlarni tozalash."""
    now = datetime.now()
    to_delete = [
        k for k, data in _agent_attempts.items()
        if data["locked_until"] is not None and data["locked_until"] < now
    ]
    for k in to_delete:
        del _agent_attempts[k]


def is_agent_blocked(identifier: str) -> tuple[bool, int]:
    """Agent identifikator (telefon yoki username) bloklangan bo'lsa qaytadi.
    Qaytadi: (blocked, remaining_seconds)
    """
    if not identifier:
        return False, 0
    with _agent_lock:
        _agent_cleanup()
        data = _agent_attempts.get(identifier)
        if not data:
            return False, 0
        if data["locked_until"] and datetime.now() < data["locked_until"]:
            remaining = int((data["locked_until"] - datetime.now()).total_seconds())
            return True, remaining
        return False, 0


def record_agent_failure(identifier: str):
    """Agent login urinishi muvaffaqiyatsiz — qayd etish va kerak bo'lsa bloklash."""
    if not identifier:
        return
    with _agent_lock:
        data = _agent_attempts.setdefault(identifier, {"count": 0, "locked_until": None})
        if data["locked_until"] and datetime.now() >= data["locked_until"]:
            data["count"] = 0
            data["locked_until"] = None
        data["count"] += 1
        if data["count"] >= AGENT_MAX_ATTEMPTS:
            data["locked_until"] = datetime.now() + timedelta(minutes=AGENT_LOCKOUT_MINUTES)


def record_agent_success(identifier: str):
    """Agent muvaffaqiyatli login — hisoblagichni sifirla."""
    if not identifier:
        return
    with _agent_lock:
        _agent_attempts.pop(identifier, None)
