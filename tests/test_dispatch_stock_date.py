"""Dispatch (yo'lga chiqarish) stock harakati sanasi YOZILGAN kunga emas, YO'LGA CHIQQAN
kunga yozilishi kerak (orqaga-sana tarixiy qoldiqni buzmasligi uchun).

apply_sale_stock_deduction endi movement_date parametrini oladi (dispatch lahzasi).
"""
from datetime import datetime


def test_apply_sale_stock_deduction_uses_movement_date(db):
    from app.models.database import Order, OrderItem, Product, Warehouse, Stock, StockMovement
    from app.services.stock_service import apply_sale_stock_deduction

    w = Warehouse(name="W", is_active=True)
    pr = Product(name="P", is_active=True)
    db.add_all([w, pr]); db.flush()
    db.add(Stock(warehouse_id=w.id, product_id=pr.id, quantity=100)); db.flush()
    # Buyurtma 06-03 da yozilgan
    o = Order(number="AGT-DSP", date=datetime(2026, 6, 3, 10, 0), type="sale", source="agent",
              warehouse_id=w.id, total=5000, paid=0, debt=5000, status="out_for_delivery")
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=5, price=1000, total=5000, warehouse_id=w.id))
    db.flush()

    # 06-05 da yo'lga chiqariladi
    dispatch_time = datetime(2026, 6, 5, 14, 30)
    apply_sale_stock_deduction(db, o, None, note_prefix="dispatch", movement_date=dispatch_time)
    db.flush()

    mv = db.query(StockMovement).filter(
        StockMovement.document_id == o.id, StockMovement.operation_type == "sale"
    ).first()
    assert mv is not None
    assert mv.created_at == dispatch_time, \
        f"Harakat YO'LGA CHIQQAN sanaga (06-05) yozilishi kerak, order.date(06-03) ga emas. Keldi: {mv.created_at}"


def test_apply_sale_stock_deduction_defaults_to_now_not_order_date(db):
    """movement_date berilmasa ham order.date (eski sana) ishlatilmaydi — now() ishlatiladi."""
    from app.models.database import Order, OrderItem, Product, Warehouse, Stock, StockMovement
    from app.services.stock_service import apply_sale_stock_deduction

    w = Warehouse(name="W2", is_active=True)
    pr = Product(name="P2", is_active=True)
    db.add_all([w, pr]); db.flush()
    db.add(Stock(warehouse_id=w.id, product_id=pr.id, quantity=100)); db.flush()
    o = Order(number="AGT-DSP2", date=datetime(2026, 6, 3, 10, 0), type="sale", source="agent",
              warehouse_id=w.id, total=2000, paid=0, debt=2000, status="out_for_delivery")
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=2, price=1000, total=2000, warehouse_id=w.id))
    db.flush()

    apply_sale_stock_deduction(db, o, None, note_prefix="dispatch")
    db.flush()
    mv = db.query(StockMovement).filter(
        StockMovement.document_id == o.id, StockMovement.operation_type == "sale"
    ).first()
    assert mv is not None
    # order.date (06-03) ga TENG bo'lmasligi kerak (now ishlatilgan)
    assert mv.created_at.date() != o.date.date(), \
        f"order.date(06-03) ishlatilmasligi kerak, keldi: {mv.created_at}"
