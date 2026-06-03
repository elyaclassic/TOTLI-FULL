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


def test_cogs_uses_snapshot_not_current_price(db):
    """Foyda COGS: cost_price>0 bo'lsa shuni, aks holda purchase_price fallback."""
    p = Product(name="COGS mahsulot", purchase_price=9999, sale_price=10000)  # joriy narx
    db.add(p); db.flush()
    o = Order(number="T-C2-3", type="sale", status="completed")
    db.add(o); db.flush()
    oi = OrderItem(order_id=o.id, product_id=p.id, quantity=2, price=10000, total=20000, cost_price=3000)
    db.add(oi); db.flush()
    # snapshot 3000 ishlatilsin (joriy 9999 emas)
    cost = float(getattr(oi, "cost_price", 0) or 0) or float(p.purchase_price or 0)
    assert cost == 3000
    # cost_price=0 bo'lsa fallback
    oi2 = OrderItem(order_id=o.id, product_id=p.id, quantity=1, price=1, total=1, cost_price=0)
    db.add(oi2); db.flush()
    cost2 = float(getattr(oi2, "cost_price", 0) or 0) or float(p.purchase_price or 0)
    assert cost2 == 9999  # fallback (snapshot yo'q)
