"""Sotuv summasi formula variantlari snapshot — deploy delta prognoz/tasdiq.

DB o'zgarmaydi (faqat kod o'zgaradi). Bu skript bir vaqtning o'zida ESKI va
YANGI formulalarni hisoblab, kutilgan deltani ko'rsatadi. Deploy oldidan
ishga tushiring, deltani yozib oling; deploy keyin hisobotlardagi raqamlar
YANGI ustunga mos kelishini tasdiqlang.

Ishlatish:
    python scripts/sales_metrics_snapshot.py                # CWD'dagi totli_holva.db
    python scripts/sales_metrics_snapshot.py <db_path>      # aniq yo'l
"""
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.database import Order
from app.services.sales_metrics import SALE_REALIZED

PERIODS = [
    (
        "Joriy oy (01..bugun)",
        datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        datetime.now().replace(hour=23, minute=59, second=59, microsecond=0),
    ),
    ("2026-05-01..2026-05-15", datetime(2026, 5, 1), datetime(2026, 5, 15, 23, 59, 59)),
]


def _sum(q):
    return float(q.with_entities(func.coalesce(func.sum(Order.total), 0)).scalar() or 0)


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "totli_holva.db"
    if not Path(db_path).exists():
        print(f"XATO: DB topilmadi: {db_path}")
        print("Ishlatish: python scripts/sales_metrics_snapshot.py <db_path>")
        sys.exit(1)
    engine = create_engine(f"sqlite:///{db_path}")
    db = sessionmaker(bind=engine)()
    try:
        print(f"DB: {db_path}")
        print(f"YANGI realized ta'rifi: {SALE_REALIZED}")
        for label, a, b in PERIODS:
            base = db.query(Order).filter(Order.type == "sale", Order.date >= a, Order.date <= b)
            new_realized = _sum(base.filter(Order.status.in_(SALE_REALIZED)))
            old_all = _sum(base)
            old_non_cancelled = _sum(base.filter(Order.status != "cancelled"))
            print(f"\n=== {label} ===")
            print(f"  YANGI realized (sales/profit/savdo total): {new_realized:>18,.0f}")
            print(f"  ESKI savdo total (hammasi, cancelled ham):  {old_all:>18,.0f}"
                  f"   delta {new_realized - old_all:>+15,.0f}")
            print(f"  ESKI profit revenue (status != cancelled):  {old_non_cancelled:>18,.0f}"
                  f"   delta {new_realized - old_non_cancelled:>+15,.0f}")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
