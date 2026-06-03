"""Test: compute_partner_balance — agent buyurtmalari faqat delivered/completed da qarz.
Dizayn: agent qarzi YETKAZISHDA yoziladi (delivery_routes oqimi). confirmed/out_for_delivery hali qarz emas.
Oddiy (POS/web) sotuvlar gating'siz (avvalgidek) sanaladi."""
from app.models.database import Partner, Order
from app.services.partner_balance_service import compute_partner_balance


def _mk_order(db, partner_id, *, source, status, total, type="sale", number):
    o = Order(number=number, type=type, partner_id=partner_id, status=status,
              total=total, subtotal=total, source=source)
    db.add(o)
    return o


def test_agent_confirmed_order_not_counted(db):
    p = Partner(name="Agent mijoz A"); db.add(p); db.flush()
    _mk_order(db, p.id, source="agent", status="confirmed", total=1_000_000, number="AGT-T-1")
    db.flush()
    # confirmed agent order — hali yetkazilmagan → qarz EMAS
    assert compute_partner_balance(db, p.id) == 0.0


def test_agent_out_for_delivery_not_counted(db):
    p = Partner(name="Agent mijoz B"); db.add(p); db.flush()
    _mk_order(db, p.id, source="agent", status="out_for_delivery", total=500_000, number="AGT-T-2")
    db.flush()
    assert compute_partner_balance(db, p.id) == 0.0


def test_agent_delivered_order_counted(db):
    p = Partner(name="Agent mijoz C"); db.add(p); db.flush()
    _mk_order(db, p.id, source="agent", status="delivered", total=750_000, number="AGT-T-3")
    db.flush()
    # delivered agent order → qarz yoziladi
    assert compute_partner_balance(db, p.id) == 750_000.0


def test_nonagent_confirmed_order_still_counted(db):
    """Oddiy (POS/web) sotuv gating'siz — confirmed bo'lsa ham sanaladi."""
    p = Partner(name="Oddiy mijoz D"); db.add(p); db.flush()
    _mk_order(db, p.id, source="web", status="confirmed", total=300_000, number="WEB-T-1")
    db.flush()
    assert compute_partner_balance(db, p.id) == 300_000.0


def test_agent_delivered_return_reduces_debt(db):
    """Agent delivered sotuv + delivered return_sale = farq."""
    p = Partner(name="Agent mijoz E"); db.add(p); db.flush()
    _mk_order(db, p.id, source="agent", status="delivered", total=1_000_000, number="AGT-T-4")
    _mk_order(db, p.id, source="agent", status="delivered", total=200_000, type="return_sale", number="AGT-T-5")
    # confirmed return — hali qarzga ta'sir qilmaydi
    _mk_order(db, p.id, source="agent", status="confirmed", total=99_000, type="return_sale", number="AGT-T-6")
    db.flush()
    assert compute_partner_balance(db, p.id) == 800_000.0   # 1,000,000 - 200,000
