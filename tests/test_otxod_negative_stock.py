"""H2: otxod/utilizatsiya strict_negative — stock yetmasa NegativeStockError (manfiy bo'lmaydi)."""
import pytest
from app.models.database import Product, Warehouse, Stock
from app.services.stock_service import create_stock_movement, NegativeStockError


def _seed(db, name, qty):
    wh = Warehouse(name=f"Test ombor {name}", is_active=True)
    db.add(wh)
    p = Product(name=f"Test mahsulot {name}", purchase_price=1000)
    db.add(p); db.flush()
    create_stock_movement(db=db, warehouse_id=wh.id, product_id=p.id, quantity_change=qty,
                          operation_type="initial_balance", document_type="Test", document_id=1,
                          document_number="T-1")
    db.flush()
    return wh, p


def test_strict_negative_rejects_oversized_removal(db):
    wh, p = _seed(db, "H2a", 3)
    with pytest.raises(NegativeStockError):
        create_stock_movement(db=db, warehouse_id=wh.id, product_id=p.id, quantity_change=-5,
                              operation_type="utilizatsiya", document_type="Test", document_id=2,
                              document_number="T-2", strict_negative=True)


def test_strict_negative_allows_exact_removal(db):
    wh, p = _seed(db, "H2b", 3)
    create_stock_movement(db=db, warehouse_id=wh.id, product_id=p.id, quantity_change=-3,
                          operation_type="utilizatsiya", document_type="Test", document_id=2,
                          document_number="T-2", strict_negative=True)
    db.flush()
    s = db.query(Stock).filter(Stock.warehouse_id == wh.id, Stock.product_id == p.id).first()
    assert float(s.quantity or 0) == 0
