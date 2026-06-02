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


from app.models.database import AuditLog
from app.services.stock_service import reconcile_stock


def test_reconcile_sets_stored_to_ledger(db):
    _wh(db); _prod(db)
    s = Stock(warehouse_id=1, product_id=1, quantity=999)
    db.add(s); db.commit()
    _mv(db, 1, 1, +100)
    _mv(db, 1, 1, -30)
    old, new = reconcile_stock(db, 1, 1, reason="test"); db.commit()
    assert old == 999.0
    assert new == 70.0
    db.refresh(s); assert s.quantity == 70.0


def test_reconcile_writes_audit(db):
    _wh(db); _prod(db)
    db.add(Stock(warehouse_id=1, product_id=1, quantity=0)); db.commit()
    _mv(db, 1, 1, +50)
    reconcile_stock(db, 1, 1, reason="transfer_confirm", actor="admin"); db.commit()
    logs = db.query(AuditLog).filter(AuditLog.entity_type == "stock").all()
    assert len(logs) == 1
    assert "transfer_confirm" in (logs[0].details or "")


def test_reconcile_no_movements_is_noop(db):
    _wh(db); _prod(db)
    s = Stock(warehouse_id=1, product_id=1, quantity=100)
    db.add(s); db.commit()
    old, new = reconcile_stock(db, 1, 1, reason="test"); db.commit()
    assert old == 100.0 and new == 100.0
    db.refresh(s); assert s.quantity == 100.0


def test_reconcile_idempotent(db):
    _wh(db); _prod(db)
    db.add(Stock(warehouse_id=1, product_id=1, quantity=0)); db.commit()
    _mv(db, 1, 1, +42)
    reconcile_stock(db, 1, 1, reason="x"); db.commit()
    old, new = reconcile_stock(db, 1, 1, reason="x"); db.commit()
    assert old == new == 42.0


def test_reconcile_fixes_transfer_churn_drift(db):
    """QLD adjustment + transfer churn → stored noto'g'ri bo'lsa ham reconcile ledger'ga tushiradi."""
    _wh(db, 2); _prod(db, 249)
    # Movement ledger: QLD +235.65, transfer churn (net 0), OT-0002/0004 out, production
    for ch in [235.65, -32.5, +32.5, -32.5, +32.5, -32.5, -32.5, -2.5, -20, -10, +66.96, -3.7, -5.35, -6.56]:
        _mv(db, 2, 249, ch, op="adjustment")
    # Stored noto'g'ri (drift simulatsiyasi)
    s = Stock(warehouse_id=2, product_id=249, quantity=254.50)
    db.add(s); db.commit()
    old, new = reconcile_stock(db, 2, 249, reason="data_fix"); db.commit()
    assert abs(old - 254.50) < 0.01
    assert abs(new - 189.50) < 0.01   # ledger = jismoniy haqiqat
    db.refresh(s); assert abs(s.quantity - 189.50) < 0.01
