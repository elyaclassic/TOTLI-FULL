"""Partner balans drift fix — raw SQL status UPDATE'dan keyin compute fresh o'qisin.

Ildiz-sabab: driver "Yetkazdim" oqimi raw `UPDATE orders SET status='delivered'`
qiladi, lekin ORM identity-map'dagi order obyekti eski status bilan qoladi.
compute_partner_balance ORM query qilganda eski statusli obyektni qaytaradi →
yangi yetkazilgan agent order hisobga olinmaydi → kesh order summasi qadar KAM
(manfiy drift). Fix: compute Order query'siga populate_existing() qo'shiladi.
"""
from datetime import datetime
from sqlalchemy import text


def test_compute_fresh_after_raw_status_update(db, sample_partner):
    """Raw SQL bilan status delivered qilingach (ORM stale), compute uni hisoblashi kerak."""
    from app.models.database import Order
    from app.services.partner_balance_service import compute_partner_balance

    o = Order(
        number="AGT-DRIFT-1", date=datetime(2026, 6, 4), type="sale",
        source="agent", status="out_for_delivery",
        partner_id=sample_partner.id, total=2_800_000, paid=0,
    )
    db.add(o)
    db.commit()

    # Order'ni identity-map'ga yuklaymiz (eski status bilan)
    loaded = db.query(Order).filter(Order.id == o.id).first()
    assert loaded.status == "out_for_delivery"
    # Agent out_for_delivery → hali qarz EMAS
    assert compute_partner_balance(db, sample_partner.id) == 0.0

    # driver_deliver kabi: raw UPDATE + flush (caller pattern)
    db.execute(text("UPDATE orders SET status='delivered' WHERE id=:id"), {"id": o.id})
    db.flush()

    # FIX: compute populate_existing bilan fresh o'qiydi → endi 2.8M qarz
    assert compute_partner_balance(db, sample_partner.id) == 2_800_000.0


def test_compute_payment_credit_after_raw_update(db, sample_partner):
    """Sotuv delivered + to'lov → balans = total - to'lov (fresh o'qish bilan)."""
    from app.models.database import Order, Payment
    from app.services.partner_balance_service import compute_partner_balance

    o = Order(
        number="AGT-DRIFT-2", date=datetime(2026, 6, 4), type="sale",
        source="agent", status="out_for_delivery",
        partner_id=sample_partner.id, total=1_000_000, paid=0,
    )
    db.add(o)
    db.add(Payment(number="P-DRIFT-2", date=datetime(2026, 6, 4), type="income",
                   partner_id=sample_partner.id, amount=400_000, status="confirmed"))
    db.commit()
    db.query(Order).filter(Order.id == o.id).first()  # identity-map'ga

    db.execute(text("UPDATE orders SET status='delivered' WHERE id=:id"), {"id": o.id})
    db.flush()

    # 1,000,000 (delivered) - 400,000 (to'lov) = 600,000
    assert compute_partner_balance(db, sample_partner.id) == 600_000.0
