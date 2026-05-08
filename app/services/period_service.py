"""Davr (Period) service — yopilgan oylar tekshiruvi.

C3 audit cleanup: avval period_close.py'da edi, ammo o'sha fayl
HTTP route'lar admin.py bilan kolliziyada edi (dead code). Helper
shu yerga ko'chirildi, route'lar admin.py'da yagona qoldi.
"""
from sqlalchemy.orm import Session

from app.models.database import ClosedPeriod


def is_period_closed(db: Session, date) -> bool:
    """Berilgan sana yopilgan davrga tegishli ekanini tekshiradi."""
    if not date:
        return False
    if isinstance(date, str):
        period = date[:7]
    else:
        period = date.strftime("%Y-%m")
    return db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first() is not None
