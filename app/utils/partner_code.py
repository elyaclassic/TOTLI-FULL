"""Kontragent (Partner) uchun avtomatik kod generatsiyasi.

Mavjud kodlar `P0001`, `P0250` ... formatida (P + ketma-ket raqam). Kod bo'sh
qoldirilsa NULL qolardi (hisobotlarda bo'sh ko'rinardi) — bu helper keyingi
bo'sh P-kodni beradi.
"""
from app.models.database import Partner


def generate_partner_code(db) -> str:
    """Keyingi bo'sh P-kod: mavjud eng katta P<raqam> dan +1 (P0001 formatida)."""
    rows = db.query(Partner.code).filter(Partner.code.like("P%")).all()
    mx = 0
    for (c,) in rows:
        if c and len(c) > 1 and c[1:].isdigit():
            mx = max(mx, int(c[1:]))
    return f"P{mx + 1:04d}"
