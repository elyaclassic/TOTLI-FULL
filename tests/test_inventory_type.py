"""StockAdjustmentDoc.type ustuni regressiya testlari."""
from datetime import datetime
from app.models.database import StockAdjustmentDoc


def test_type_column_defaults_to_inventory(db):
    doc = StockAdjustmentDoc(
        number="INV-TEST-1", date=datetime.now(),
        warehouse_id=1, user_id=1, status="draft",
    )
    db.add(doc); db.commit()
    db.refresh(doc)
    assert doc.type == "inventory", "default tur Inventarizatsiya bo'lishi kerak"


def test_type_column_accepts_stock_entry(db):
    doc = StockAdjustmentDoc(
        number="INV-TEST-2", date=datetime.now(),
        warehouse_id=1, user_id=1, status="draft", type="stock_entry",
    )
    db.add(doc); db.commit()
    db.refresh(doc)
    assert doc.type == "stock_entry"


def test_ensure_helper_idempotent(db):
    from app.utils.db_schema import ensure_stock_adjustment_doc_type_column
    # In-memory DB'da model orqali ustun allaqachon bor; helper xato bermasligi kerak
    ensure_stock_adjustment_doc_type_column(db)
    ensure_stock_adjustment_doc_type_column(db)  # 2-marta — duplicate column ushlanishi kerak
