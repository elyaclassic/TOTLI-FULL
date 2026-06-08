"""Production qayta-tasdiqlash timestamp — soxta "Dublikat yozuv" oldini olish.

Revert'dan keyin qayta-tasdiqlanganda yangi stock harakatlari asl production.created_at
bilan yozilsa, 1-tasdiq harakatlari bilan bayt-bayt bir xil bo'lib jurnalda dublikatdek
ko'rinadi (qoldiqqa ta'siri yo'q). _production_movement_ts revert mavjud bo'lsa now()
qaytaradi → harakatlar farqlanadi.
"""
from datetime import datetime
from app.models.database import Production, StockMovement
from app.routes.production import _production_movement_ts

_PAST = datetime(2026, 6, 8, 13, 41, 8)


def _mk(db, number):
    p = Production(number=number, quantity=1, status="draft", created_at=_PAST)
    db.add(p)
    db.flush()
    return p


def test_first_confirm_uses_created_at(db):
    p = _mk(db, "PR-TS-1")
    assert _production_movement_ts(db, p) == _PAST, "birinchi tasdiq production.created_at ishlatsin"


def test_reconfirm_after_revert_uses_now(db):
    p = _mk(db, "PR-TS-2")
    db.add(StockMovement(
        warehouse_id=6, product_id=250, quantity_change=1.4,
        operation_type="production_revert", document_type="Production",
        document_id=p.id, document_number="PR-TS-2", quantity_after=0,
        created_at=datetime(2026, 6, 8, 16, 22),
    ))
    db.flush()
    ts = _production_movement_ts(db, p)
    assert ts != _PAST, "qayta-tasdiqda asl created_at takrorlanmasligi kerak (dublikat ko'rinmasin)"
    assert ts > _PAST, "qayta-tasdiq ts now() bo'lishi kerak (revert'dan keyin)"
