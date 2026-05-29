from datetime import datetime

from app.models.database import Partner, CustomerBotLink
from app.bot.customer_bot.phone import normalize_phone


def find_matching_partners(db, phone):
    """Telefon mos keluvchi aktiv partnerlar ro'yxati (phone yoki phone2)."""
    norm = normalize_phone(phone)
    if not norm:
        return []
    partners = db.query(Partner).filter(Partner.is_active == True).all()  # noqa: E712
    return [
        p for p in partners
        if normalize_phone(p.phone) == norm or normalize_phone(p.phone2) == norm
    ]
