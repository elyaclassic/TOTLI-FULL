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


def ensure_agents_pin_hash_column(db: Session) -> None:
    """Agar agents jadvalida pin_hash ustuni bo'lmasa, qo'shadi.
    Agent login PIN (B3) uchun — null default (backward compat: legacy phone-as-password)."""
    try:
        db.execute(text("ALTER TABLE agents ADD COLUMN pin_hash VARCHAR(255) DEFAULT NULL"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_agents_pin_set_at_column(db: Session) -> None:
    """agents.pin_set_at — PIN qachon o'rnatilgan (audit uchun)."""
    try:
        db.execute(text("ALTER TABLE agents ADD COLUMN pin_set_at DATETIME DEFAULT NULL"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_employee_quota_column(db: Session) -> None:
    """employees.monthly_free_quota — oyiga bepul mahsulot kvotasi (so'm)."""
    try:
        db.execute(text("ALTER TABLE employees ADD COLUMN monthly_free_quota FLOAT DEFAULT 90000"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_advance_is_product_column(db: Session) -> None:
    """employee_advances.is_product — mahsulot avansi (kvota qo'llanadi)."""
    try:
        db.execute(text("ALTER TABLE employee_advances ADD COLUMN is_product BOOLEAN DEFAULT 0"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()


def ensure_audit_cooldowns_table(db: Session) -> None:
    """audit_cooldowns jadvali — audit watchdog dedup/cooldown saqlanadi.
    Process restart paytida ham saqlanadi (B5 — O5 fix)."""
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_cooldowns (
                key VARCHAR(255) PRIMARY KEY,
                last_sent_at DATETIME NOT NULL
            )
        """))
        db.commit()
    except Exception:
        db.rollback()
