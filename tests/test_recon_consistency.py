"""Akt-sverki (partner reconciliation) ending balance compute_partner_balance bilan mos kelishi kerak.

Bug: _build_partner_movements agent orderni har qanday non-cancelled/draft statusda
sanaydi (confirmed/out_for_delivery ham), lekin compute_partner_balance agent orderni
faqat delivered/completed da sanaydi → recon closing balance haqiqiy balansdan farq
qiladi (obmen confirmed return → recon 0 ko'rsatadi, haqiqiy balans esa qarz).
"""
from datetime import datetime


def _recon_closing(db, partner_id):
    from app.routes.reports import _build_partner_movements
    rows, od, oc = _build_partner_movements(
        db, partner_id, datetime(2026, 1, 1), datetime(2030, 1, 1), period_only=False
    )
    return (od - oc) + sum(r["debit"] for r in rows) - sum(r["credit"] for r in rows)


def test_recon_matches_balance_with_confirmed_agent_return(db, sample_partner):
    """Obmen: delivered agent sotuv + confirmed (yetkazilmagan) agent qaytarish.
    Recon closing == compute_partner_balance (qaytarish krediti hali qo'llanmaydi)."""
    from app.models.database import Order
    from app.services.partner_balance_service import compute_partner_balance

    # delivered agent sotuv (yangi tovar) → qarz +56k
    db.add(Order(number="AGT-S", date=datetime(2026, 6, 4), type="sale", source="agent",
                 status="delivered", partner_id=sample_partner.id, total=56000, paid=0))
    # confirmed agent qaytarish (eski tovar, yetkazilmagan) → hali kredit EMAS
    db.add(Order(number="AGT-R", date=datetime(2026, 6, 4), type="return_sale", source="agent",
                 status="confirmed", partner_id=sample_partner.id, total=56000, paid=0))
    db.commit()

    bal = compute_partner_balance(db, sample_partner.id)
    assert bal == 56000.0  # faqat delivered sotuv sanaladi
    assert _recon_closing(db, sample_partner.id) == bal  # recon ham mos kelishi kerak


def test_recon_excludes_confirmed_agent_sale(db, sample_partner):
    """Confirmed (yetkazilmagan) agent sotuv hali qarz emas — recon ham sanamasin."""
    from app.models.database import Order
    from app.services.partner_balance_service import compute_partner_balance

    db.add(Order(number="AGT-OFD", date=datetime(2026, 6, 4), type="sale", source="agent",
                 status="out_for_delivery", partner_id=sample_partner.id, total=100000, paid=0))
    db.commit()

    assert compute_partner_balance(db, sample_partner.id) == 0.0
    assert _recon_closing(db, sample_partner.id) == 0.0
