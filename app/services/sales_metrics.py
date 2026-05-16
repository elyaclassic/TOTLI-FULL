"""Sotuv metrikalari — YAGONA HAQIQAT MANBAI.

Tizimda "sotuv summasi" 4 endpoint'da 4 xil hisoblanardi (status/sana drift).
Bu modul ta'rifni bitta joyga qulflaydi. finance_service.cash_balance_formula
etalon uslubi: ta'rif shu yerda, shakl (paginatsiya/JOIN/agregat) endpoint'da.
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.database import Order

# Daromad/foyda hisoblanadigan sotuv holatlari — YAGONA ta'rif.
# Modul tashqarisida Order.status.in_(...) yozilmaydi.
SALE_REALIZED = ("delivered", "completed", "confirmed")


def sale_orders_query(
    db: Session,
    *,
    scope: str = "realized",
    dt_from=None,
    dt_to=None,
    warehouse_id: Optional[int] = None,
    partner_id: Optional[int] = None,
) -> Query:
    """type=='sale' Order query'si. Sana doimo Order.date (biznes sanasi).

    scope='realized' -> status IN SALE_REALIZED
    scope='all'      -> status filtri yo'q (cancelled ham; operatsion ro'yxat)

    Qaytgan Query'ni endpoint o'zi kengaytiradi (paginate/JOIN/agregat).
    """
    if scope not in ("realized", "all"):
        raise ValueError(f"noma'lum scope: {scope!r}")
    q = db.query(Order).filter(Order.type == "sale")
    if scope == "realized":
        q = q.filter(Order.status.in_(SALE_REALIZED))
    if dt_from is not None:
        q = q.filter(Order.date >= dt_from)
    if dt_to is not None:
        q = q.filter(Order.date <= dt_to)
    if warehouse_id:
        q = q.filter(Order.warehouse_id == warehouse_id)
    if partner_id:
        q = q.filter(Order.partner_id == partner_id)
    return q


def sale_revenue(
    db: Session,
    *,
    dt_from,
    dt_to,
    warehouse_id: Optional[int] = None,
    partner_id: Optional[int] = None,
) -> float:
    """realized scope bo'yicha Sum(Order.total) — bitta skalyar."""
    q = sale_orders_query(
        db,
        scope="realized",
        dt_from=dt_from,
        dt_to=dt_to,
        warehouse_id=warehouse_id,
        partner_id=partner_id,
    )
    val = q.with_entities(func.coalesce(func.sum(Order.total), 0)).scalar()
    return float(val or 0)
