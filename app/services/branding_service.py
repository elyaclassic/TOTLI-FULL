"""Brending (logo) sozlamalari servisi.

resolve_branding(db) -> sof funksiya, DB'dan logo yo'llarini o'qiydi, fayl
mavjudligini tekshiradi, yo'q bo'lsa standartga qaytadi.
"""
import os

BRANDING_KEYS = ("logo_main", "logo_circle")

DEFAULTS = {
    "logo_main": "/static/images/logo.png",
    "logo_circle": "/static/images/logo_circle.png",
}

BRANDING_DIR = os.path.join("app", "static", "images", "branding")


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
