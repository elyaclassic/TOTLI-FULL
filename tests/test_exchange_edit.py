from datetime import datetime
from app.models.database import Order, OrderItem, Partner, Product, Unit
from app.routes.sales import _exchange_editable, _apply_exchange_edit


def _exchange(db, *, ret_lines, new_lines, status="confirmed"):
    u = Unit(name="kg"); db.add(u); db.flush()
    p = Partner(name="Mijoz", phone="+1", balance=0, is_active=True); db.add(p); db.flush()
    def _mkprod(pid):
        pr = db.query(Product).filter(Product.id == pid).first()
        if not pr:
            pr = Product(id=pid, name=f"P{pid}", unit_id=u.id, is_active=True); db.add(pr); db.flush()
        return pr
    parent = Order(number="AGT-R", type="return_sale", status=status, partner_id=p.id,
                   subtotal=0, total=0, paid=0, debt=0, date=datetime(2026,6,1))
    db.add(parent); db.flush()
    child = Order(number="AGT-S", type="sale", status=status, partner_id=p.id, parent_order_id=parent.id,
                  subtotal=0, total=0, paid=0, debt=0, date=datetime(2026,6,1))
    db.add(child); db.flush()
    for o, lines in ((parent, ret_lines), (child, new_lines)):
        tot = 0.0
        for pid, qty, price in lines:
            _mkprod(pid)
            db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty, price=price, total=qty*price))
            tot += qty*price
        o.subtotal = tot; o.total = tot
    db.commit()
    return parent, child, p


def test_editable_confirmed_true(db):
    parent, child, _ = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)], status="confirmed")
    assert _exchange_editable(parent, child) is True


def test_editable_delivered_false(db):
    parent, child, _ = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)], status="delivered")
    assert _exchange_editable(parent, child) is False


def test_apply_edit_replaces_items_and_total(db):
    parent, child, p = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)])
    _apply_exchange_edit(db, parent, child,
                         ret_lines=[(1,5,43000)], new_lines=[(2,5,43000)], actor="admin")
    db.commit()
    db.refresh(child)
    items = db.query(OrderItem).filter(OrderItem.order_id == child.id).all()
    assert len(items) == 1 and items[0].product_id == 2
    assert child.total == 215000.0


def test_apply_edit_unequal_affects_balance(db):
    parent, child, p = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)])
    _apply_exchange_edit(db, parent, child,
                         ret_lines=[(1,5,43000)], new_lines=[(1,5,43000),(2,1,100000)], actor="admin")
    db.commit()
    db.refresh(p)
    assert p.balance == 100000.0


def test_apply_edit_equal_balance_zero(db):
    parent, child, p = _exchange(db, ret_lines=[(1,5,43000)], new_lines=[(1,5,43000)])
    _apply_exchange_edit(db, parent, child,
                         ret_lines=[(3,2,50000)], new_lines=[(3,2,50000)], actor="admin")
    db.commit()
    db.refresh(p)
    assert p.balance == 0.0
