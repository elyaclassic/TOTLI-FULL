"""D1 regressiya: is_stock_entry mexanikasi (SET vs ADD).

Bu testlar _apply_inventory_stock_changes ning ikkala rejimi to'g'ri ishlashini
tasdiqlaydi. doc.type'dan is_stock_entry o'qish Task 6'da bo'ladi; bu yerda
faqat mexanika tekshiriladi (parametr sifatida uzatib).
"""
from datetime import datetime, timedelta
from app.models.database import (
    StockAdjustmentDoc, StockAdjustmentDocItem, Stock, StockMovement,
    Product, Warehouse,
)
from app.routes.warehouse import _apply_inventory_stock_changes


def _setup_stock(db, wh_id: int, prod_id: int, code: str, quantity: float):
    """Stock=quantity, ledger=quantity (initial_balance bilan moslangan)."""
    db.add(Warehouse(id=wh_id, name="T", is_active=True))
    db.add(Product(id=prod_id, code=code, name="T", is_active=True))
    s = Stock(warehouse_id=wh_id, product_id=prod_id, quantity=quantity)
    db.add(s); db.flush()
    db.add(StockMovement(
        stock_id=s.id, warehouse_id=wh_id, product_id=prod_id,
        operation_type="initial_balance", document_type="InitialBalance",
        document_id=0, document_number="INIT-T",
        quantity_change=quantity, quantity_after=quantity,
        created_at=datetime.now() - timedelta(days=1),
    ))
    db.flush()


def test_type_inventory_does_set(db):
    """type='inventory' -> SET: stock = jismoniy (50), eski 100 ga qaramay."""
    _setup_stock(db, wh_id=98, prod_id=998, code="P-S", quantity=100.0)
    doc = StockAdjustmentDoc(
        number="INV-PENDING-X", date=datetime.now(),
        warehouse_id=98, status="draft", type="inventory",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(
        doc_id=doc.id, warehouse_id=98, product_id=998, quantity=50.0,
    ))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=False, current_user=None)
    db.commit()
    s = db.query(Stock).filter_by(warehouse_id=98, product_id=998).first().quantity
    assert abs(float(s) - 50.0) < 1e-3, f"SET kutilgan 50, oldi {s}"


def test_type_stock_entry_does_add(db):
    """type='stock_entry' -> ADD: stock = old(100) + new(50) = 150."""
    _setup_stock(db, wh_id=97, prod_id=997, code="P-A", quantity=100.0)
    doc = StockAdjustmentDoc(
        number="INV-PENDING-Y", date=datetime.now(),
        warehouse_id=97, status="draft", type="stock_entry",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(
        doc_id=doc.id, warehouse_id=97, product_id=997, quantity=50.0,
    ))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=True, current_user=None)
    db.commit()
    s = db.query(Stock).filter_by(warehouse_id=97, product_id=997).first().quantity
    assert abs(float(s) - 150.0) < 1e-3, f"ADD kutilgan 150 (100+50), oldi {s}"
