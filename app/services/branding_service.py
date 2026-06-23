"""Brending (logo) sozlamalari servisi.

resolve_branding(db) -> sof funksiya, DB'dan logo yo'llarini o'qiydi, fayl
mavjudligini tekshiradi, yo'q bo'lsa standartga qaytadi.
"""
import os
import time

BRANDING_KEYS = ("logo_main", "logo_circle")

DEFAULTS = {
    "logo_main": "/static/images/logo.png",
    "logo_circle": "/static/images/logo_circle.png",
}

BRANDING_DIR = os.path.join("app", "static", "images", "branding")

ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp"}
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def save_branding_image(slot: str, contents: bytes, ext: str) -> str:
    """Rasmni branding papkasiga timestamp nomi bilan saqlaydi. Fayl nomini qaytaradi."""
    os.makedirs(BRANDING_DIR, exist_ok=True)
    ts = int(time.time())
    filename = f"{slot}_{ts}.{ext}"
    with open(os.path.join(BRANDING_DIR, filename), "wb") as f:
        f.write(contents)
    return filename


def cleanup_old_branding(slot: str, keep: str) -> None:
    """slot prefiksli, keep'dan boshqa eski fayllarni o'chiradi."""
    try:
        if not os.path.isdir(BRANDING_DIR):
            return
        for name in os.listdir(BRANDING_DIR):
            if name.startswith(f"{slot}_") and name != keep:
                try:
                    os.remove(os.path.join(BRANDING_DIR, name))
                except OSError:
                    pass
    except Exception:
        pass


def resolve_branding(db) -> dict:
    """DB'dan logo yo'llarini o'qib qaytaradi. Fayl yo'q/yozuv yo'q -> standart."""
    result = dict(DEFAULTS)
    try:
        from app.models.database import AppSetting
        rows = (
            db.query(AppSetting)
            .filter(AppSetting.key.in_(BRANDING_KEYS))
            .all()
        )
        for row in rows:
            if not row.value:
                continue
            disk_path = os.path.join(BRANDING_DIR, row.value)
            if os.path.isfile(disk_path):
                result[row.key] = f"/static/images/branding/{row.value}"
    except Exception:
        pass
    return result


_cache = None


def _load_branding() -> dict:
    """DB session ochib resolve_branding'ni chaqiradi (runtime)."""
    from app.models.database import SessionLocal
    db = SessionLocal()
    try:
        return resolve_branding(db)
    finally:
        db.close()


def get_branding_cached() -> dict:
    """Runtime cache — Jinja global shuni ishlatadi. Kam o'zgaradi."""
    global _cache
    if _cache is None:
        _cache = _load_branding()
    return _cache


def invalidate_branding_cache() -> None:
    """Logo yangilanganda/qaytarilganda chaqiriladi."""
    global _cache
    _cache = None
