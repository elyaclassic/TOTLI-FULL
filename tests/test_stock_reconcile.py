from datetime import datetime
from app.models.database import Stock, StockMovement, Warehouse, Product, Unit
from app.services.stock_service import compute_stock_quantity


def _wh(db, wid=1):
    w = Warehouse(id=wid, name=f"WH{wid}", code=f"W{wid}")
    db.add(w); db.commit(); return w


def _prod(db, pid=1):
    u = Unit(name="kg"); db.add(u); db.flush()
    p = Product(id=pid, name=f"P{pid}", unit_id=u.id, is_active=True)
    db.add(p); db.commit(); return p


def _mv(db, wid, pid, change, op="adjustment"):
    db.add(StockMovement(warehouse_id=wid, product_id=pid, quantity_change=change,
                         quantity_after=0, operation_type=op, document_type="X",
                         document_id=1, created_at=datetime(2026, 6, 1)))
    db.commit()


def test_compute_empty_is_zero(db):
    _wh(db); _prod(db)
    assert compute_stock_quantity(db, 1, 1) == 0.0


def test_compute_sums_movements(db):
    _wh(db); _prod(db)
    _mv(db, 1, 1, +235.65)
    _mv(db, 1, 1, -32.5)
    _mv(db, 1, 1, -32.5)
    assert abs(compute_stock_quantity(db, 1, 1) - 170.65) < 1e-9


def test_compute_isolated_per_wh_product(db):
    _wh(db, 1); _wh(db, 2); _prod(db, 1); _prod(db, 2)
    _mv(db, 1, 1, +10)
    _mv(db, 2, 1, +99)
    _mv(db, 1, 2, +5)
    assert compute_stock_quantity(db, 1, 1) == 10.0
