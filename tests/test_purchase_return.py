import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.database import Base, PurchaseReturn, PurchaseReturnItem, Partner, Warehouse, Product, Stock, Unit

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()

def test_models_exist_and_persist(db):
    pr = PurchaseReturn(number="PR-20260531-0001", partner_id=1, warehouse_id=1,
                        status="draft", reason="brak", total=0.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=2.0, price=1000.0, total=2000.0))
    db.commit()
    got = db.query(PurchaseReturn).first()
    assert got.number == "PR-20260531-0001"
    assert got.items[0].total == 2000.0
