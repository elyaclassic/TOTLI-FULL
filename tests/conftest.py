"""TOTLI BI test fixtures.

In-memory SQLite ishlatadi — har test uchun toza DB.
Live `totli_holva.db` ga tegmaydi.

Asosiy fixtures:
- `db` — toza in-memory SQLite session
- `client` — FastAPI TestClient (auth bypass bilan)
- `admin_user`, `agent_user` — test foydalanuvchilar
- `sample_product`, `sample_warehouse`, `sample_partner` — test data

Ishlatish:
    pytest tests/ -v
"""
import os
import sys
from pathlib import Path

import pytest

# Test rejimi — main.py startup hooklarni o'tkazib yuborish uchun
os.environ.setdefault("TESTING", "1")

# Auth modulda SECRET_KEY majburiy — testlar uchun deterministik qiymat
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")

# Loyiha root'ni PYTHONPATH ga
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")


@pytest.fixture
def db():
    """Toza in-memory SQLite session — har test alohida."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    """TestClient bilan get_db dependency override."""
    from fastapi.testclient import TestClient
    from app.models.database import get_db
    from main import app

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ============================================================
# Sample data fixtures
# ============================================================

@pytest.fixture
def admin_user(db):
    """Admin foydalanuvchi yaratadi."""
    from app.models.database import User
    from app.utils.auth import hash_password
    u = User(
        username="test_admin",
        password_hash=hash_password("admin123"),
        full_name="Test Admin",
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def agent_user(db):
    """Agent foydalanuvchi + Agent yozuvi."""
    from app.models.database import User, Agent
    from app.utils.auth import hash_password
    u = User(
        username="test_agent",
        password_hash=hash_password("agent123"),
        full_name="Test Agent",
        role="agent",
        is_active=True,
    )
    db.add(u)
    db.flush()
    a = Agent(
        code="AG-TEST",
        full_name="Test Agent",
        phone="+998900000000",
        user_id=u.id,
        is_active=True,
    )
    db.add(a)
    db.commit()
    db.refresh(u)
    db.refresh(a)
    return u


@pytest.fixture
def sample_warehouse(db):
    from app.models.database import Warehouse
    w = Warehouse(name="Test Ombor", code="TEST-WH")
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def sample_unit(db):
    from app.models.database import Unit
    u = Unit(name="Dona")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def sample_product(db, sample_unit):
    from app.models.database import Product
    p = Product(
        name="Test Mahsulot",
        code="TEST-001",
        unit_id=sample_unit.id,
        is_active=True,
        purchase_price=10000,
        sale_price=15000,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def sample_partner(db):
    from app.models.database import Partner
    p = Partner(
        name="Test Mijoz",
        phone="+998900000001",
        balance=0,
        credit_limit=0,
        is_active=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def sample_stock(db, sample_warehouse, sample_product):
    """Test ombor + mahsulot uchun 100 dona stock yaratadi."""
    from app.models.database import Stock
    s = Stock(
        warehouse_id=sample_warehouse.id,
        product_id=sample_product.id,
        quantity=100.0,
        cost_price=10000,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture
def sample_cash(db):
    from app.models.database import CashRegister
    c = CashRegister(
        name="Test Kassa",
        payment_type="naqd",
        is_active=True,
        opening_balance=0,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
