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


import datetime as _dt

def _seed(db):
    db.add(Unit(id=1, name="dona", code="ta"))
    db.add(Warehouse(id=1, name="Xom ashyo ombori"))
    db.add(Product(id=1, name="Yong'oq", unit_id=1, purchase_price=1000.0))
    db.add(Partner(id=1, name="Shakar aka", type="supplier", balance=-50000.0))  # biz 50k qarzdormiz
    db.add(Stock(warehouse_id=1, product_id=1, quantity=10.0))
    db.commit()

def test_confirm_reduces_stock_and_debt(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return
    pr = PurchaseReturn(number="PR-20260531-0001", partner_id=1, warehouse_id=1,
                        date=_dt.datetime(2026,5,31,10,0), status="draft", reason="brak", total=3000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=3.0, price=1000.0, total=3000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    db.refresh(pr)
    assert pr.status == "confirmed"
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 7.0
    assert db.query(Partner).get(1).balance == -47000.0     # -50000 + 3000
    assert db.query(Product).get(1).purchase_price == 1000.0  # UNCHANGED

def test_cannot_return_more_than_stock(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return, DocumentError
    pr = PurchaseReturn(number="PR-20260531-0002", partner_id=1, warehouse_id=1,
                        date=_dt.datetime(2026,5,31,10,0), status="draft", total=99000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=99.0, price=1000.0, total=99000.0))
    db.commit()
    with pytest.raises(DocumentError):
        confirm_return(db, pr, current_user=None)
    db.refresh(pr)
    assert pr.status == "draft"  # validation failed BEFORE status change
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 10.0

def test_double_confirm_blocked(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return, DocumentError
    pr = PurchaseReturn(number="PR-20260531-0003", partner_id=1, warehouse_id=1,
                        date=_dt.datetime(2026,5,31,10,0), status="draft", total=1000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=1.0, price=1000.0, total=1000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    with pytest.raises(DocumentError):
        confirm_return(db, pr, current_user=None)
    assert db.query(Partner).get(1).balance == -49000.0  # applied only once

def test_cancel_restores(db):
    _seed(db)
    from app.services.purchase_return_service import confirm_return, cancel_return
    pr = PurchaseReturn(number="PR-20260531-0004", partner_id=1, warehouse_id=1,
                        date=_dt.datetime(2026,5,31,10,0), status="draft", total=2000.0)
    db.add(pr); db.flush()
    db.add(PurchaseReturnItem(return_id=pr.id, product_id=1, quantity=2.0, price=1000.0, total=2000.0))
    db.commit()
    confirm_return(db, pr, current_user=None)
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 8.0
    cancel_return(db, pr, current_user=None)
    db.refresh(pr)
    assert pr.status == "cancelled"
    assert db.query(Stock).filter_by(warehouse_id=1, product_id=1).first().quantity == 10.0  # restored
    assert db.query(Partner).get(1).balance == -50000.0  # restored
