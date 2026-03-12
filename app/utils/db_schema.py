"""Ma'lumotlar bazasi jadval ustunlarini tekshirish (migration-style)."""
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


def ensure_orders_payment_due_date_column(db: Session) -> None:
    """Agar orders jadvalida payment_due_date ustuni bo'lmasa, qo'shadi."""
    try:
        db.execute(text("ALTER TABLE orders ADD COLUMN payment_due_date DATE"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_order_item_warehouse_id_column(db: Session) -> None:
    """Agar order_items jadvalida warehouse_id ustuni bo'lmasa, qo'shadi."""
    try:
        db.execute(text("ALTER TABLE order_items ADD COLUMN warehouse_id INTEGER REFERENCES warehouses(id)"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_payments_status_column(db: Session) -> None:
    """Agar payments jadvalida status ustuni bo'lmasa, qo'shadi."""
    try:
        db.execute(text("ALTER TABLE payments ADD COLUMN status VARCHAR(20) DEFAULT 'confirmed'"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_cash_opening_balance_column(db: Session) -> None:
    """Agar cash_registers jadvalida opening_balance ustuni bo'lmasa, qo'shadi."""
    try:
        db.execute(text("ALTER TABLE cash_registers ADD COLUMN opening_balance FLOAT DEFAULT 0"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()
