"""_apply_inventory_stock_changes baseline tuzog'i regressiyasi (D2).

WH2 KAROBKA 2026-05-19 incidentini takrorlaydi: back-dated sintetik
InitialBalance qatori (eng katta ID, ancient created_at, quantity_after=axlat)
last_mv lookup'da topilib, old_qty ga axlat qaytarganda Stock buziladi.
"""
from datetime import datetime
import pytest
from sqlalchemy import text
from app.models.database import (
    StockAdjustmentDoc, StockAdjustmentDocItem,
    Stock, StockMovement, Product, Warehouse,
)
from app.routes.warehouse import _apply_inventory_stock_changes


def _setup_corrupt_baseline(db):
    """Buzuq Ledger: real stacked-INIT + sintetik DRIFT-FIX (yuqori ID, qadimiy sana)."""
    wh = Warehouse(id=99, name="Test WH", is_active=True); db.add(wh)
    prod = Product(id=999, code="P-T", name="Test KAROBKA", is_active=True); db.add(prod)
    stock = Stock(warehouse_id=99, product_id=999, quantity=-1200.0); db.add(stock)
    db.flush()
    sid = stock.id
    # Real stacked-INIT (kichik IDlar, ancient sanalar) — ledger SUM ni quradi
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="initial_balance",
        document_type="InitialBalance", document_id=0, document_number="INIT-BALANCE",
        quantity_change=2000.0, quantity_after=2000.0,
        created_at=datetime(2026, 3, 4, 14, 58, 42),
    ))
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="initial_balance",
        document_type="InitialBalance", document_id=0, document_number="INIT-BALANCE-RETRO",
        quantity_change=3000.0, quantity_after=3000.0,
        created_at=datetime(2026, 4, 13, 13, 4, 15),
    ))
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="adjustment",
        document_type="StockAdjustmentDoc", document_id=0, document_number="INV-PRIOR",
        quantity_change=-15.0, quantity_after=2970.0,
        created_at=datetime(2026, 5, 8, 18, 28, 0),
    ))
    # SINTETIK DRIFT-FIX: ancient sana LEKIN INSERT vaqti yangi (id eng katta bo'ladi)
    db.add(StockMovement(
        stock_id=sid, warehouse_id=99, product_id=999, operation_type="initial_out",
        document_type="InitialBalance", document_id=0,
        document_number="INIT-DRIFT-FIX-W99-P999-20260513",
        quantity_change=-3000.0, quantity_after=-3000.0,  # AXLAT quantity_after
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    ))
    db.commit()
    return wh, prod, stock


def test_set_mode_ignores_corrupt_quantity_after(db):
    """Inventarizatsiya (SET): jismoniy=1800 -> Stock=1800, Ledger SUM=1800."""
    wh, prod, stock = _setup_corrupt_baseline(db)
    doc = StockAdjustmentDoc(
        number="INV-T-SET", date=datetime(2026, 5, 19, 14, 53),
        warehouse_id=99, user_id=None, status="draft", type="inventory",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(
        doc_id=doc.id, warehouse_id=99, product_id=999,
        quantity=1800.0, cost_price=0.0, sale_price=0.0,
    ))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=False, current_user=None)
    db.commit()
    stock_q = db.query(Stock).filter_by(warehouse_id=99, product_id=999).first().quantity
    led = db.execute(text(
        "SELECT COALESCE(SUM(quantity_change),0) FROM stock_movements "
        "WHERE warehouse_id=99 AND product_id=999"
    )).scalar()
    assert abs(float(stock_q) - 1800.0) < 1e-3, f"Stock {stock_q} != 1800 (SET)"
    assert abs(float(led) - 1800.0) < 1e-3, f"Ledger SUM {led} != 1800 (SET)"


def test_add_mode_uses_clean_baseline(db):
    """Tovar qoldiqlari (ADD): jismoniy=1800 ustiga qo'shiladi.
    Toza baseline = SUM≤doc_date = 2000+3000-15-3000 = 1985.
    Kutilgan: Stock = 1985 + 1800 = 3785 (axlat -3000 emas)."""
    wh, prod, stock = _setup_corrupt_baseline(db)
    doc = StockAdjustmentDoc(
        number="INV-T-ADD", date=datetime(2026, 5, 19, 14, 53),
        warehouse_id=99, user_id=None, status="draft", type="stock_entry",
    )
    db.add(doc); db.flush()
    db.add(StockAdjustmentDocItem(
        doc_id=doc.id, warehouse_id=99, product_id=999,
        quantity=1800.0, cost_price=0.0, sale_price=0.0,
    ))
    db.flush(); db.refresh(doc)
    _apply_inventory_stock_changes(db, doc, is_stock_entry=True, current_user=None)
    db.commit()
    stock_q = db.query(Stock).filter_by(warehouse_id=99, product_id=999).first().quantity
    led = db.execute(text(
        "SELECT COALESCE(SUM(quantity_change),0) FROM stock_movements "
        "WHERE warehouse_id=99 AND product_id=999"
    )).scalar()
    assert abs(float(stock_q) - 3785.0) < 1e-3, f"Stock {stock_q} != 3785 (ADD)"
    assert abs(float(led) - 3785.0) < 1e-3, f"Ledger SUM {led} != 3785 (ADD)"
