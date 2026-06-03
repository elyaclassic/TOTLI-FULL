"""C2: OrderItem.cost_price sotuv vaqtidagi tan narxni qotiradi (before_insert snapshot)."""
from app.models.database import Product, Order, OrderItem


def test_orderitem_cost_snapshot(db):
    p = Product(name="Test mahsulot C2", purchase_price=5000, sale_price=8000)
    db.add(p); db.flush()
    o = Order(number="T-C2-1", type="sale", status="completed")
    db.add(o); db.flush()
    oi = OrderItem(order_id=o.id, product_id=p.id, quantity=2, price=8000, total=16000)
    db.add(oi); db.flush()
    assert float(oi.cost_price) == 5000


def test_orderitem_cost_explicit_not_overwritten(db):
    p = Product(name="Test mahsulot C2b", purchase_price=5000)
    db.add(p); db.flush()
    o = Order(number="T-C2-2", type="sale")
    db.add(o); db.flush()
    oi = OrderItem(order_id=o.id, product_id=p.id, quantity=1, price=1, total=1, cost_price=9999)
    db.add(oi); db.flush()
    assert float(oi.cost_price) == 9999
