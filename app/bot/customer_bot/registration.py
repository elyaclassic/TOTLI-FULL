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


def get_link_by_telegram(db, telegram_id):
    return db.query(CustomerBotLink).filter(
        CustomerBotLink.telegram_id == str(telegram_id)
    ).first()


def create_pending_link(db, telegram_id, username, full_name, phone):
    link = get_link_by_telegram(db, telegram_id)
    if link is None:
        link = CustomerBotLink(telegram_id=str(telegram_id))
        db.add(link)
    link.telegram_username = username
    link.telegram_full_name = full_name
    link.phone = phone
    link.status = "pending"
    link.partner_id = None
    link.requested_at = datetime.now()
    db.commit()
    db.refresh(link)
    return link


def approve_link(db, link_id, partner_id, approved_by):
    link = db.query(CustomerBotLink).filter(CustomerBotLink.id == link_id).first()
    link.status = "approved"
    link.partner_id = partner_id
    link.approved_at = datetime.now()
    link.approved_by = str(approved_by)
    db.commit()
    db.refresh(link)
    return link


def reject_link(db, link_id, approved_by):
    link = db.query(CustomerBotLink).filter(CustomerBotLink.id == link_id).first()
    link.status = "rejected"
    link.approved_by = str(approved_by)
    db.commit()
    db.refresh(link)
    return link


def approved_telegram_ids_for_partner(db, partner_id):
    rows = db.query(CustomerBotLink).filter(
        CustomerBotLink.partner_id == partner_id,
        CustomerBotLink.status == "approved",
    ).all()
    return [r.telegram_id for r in rows]
