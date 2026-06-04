from datetime import datetime, date, timedelta


def test_board_snapshot_groups_by_status(db):
    from app.models.database import Order, OrderItem, Partner, Product
    from app.services.board_service import build_board_snapshot

    p = Partner(name="Elshod Market", balance=0, code="P_B1")
    pr = Product(name="BARGELIK 400gr", is_active=True, sale_price=30000)
    db.add_all([p, pr]); db.flush()
    for st in ["confirmed", "waiting_production", "out_for_delivery"]:
        o = Order(number=f"AGT-{st}", date=datetime.now(), type="sale", source="agent",
                  partner_id=p.id, total=490000, paid=0, debt=490000, status=st,
                  delivery_date=date.today() + timedelta(days=1))
        db.add(o); db.flush()
        db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=5, price=30000, total=150000))
    db.commit()

    snap = build_board_snapshot(db)
    assert len(snap["confirmed"]) == 1
    assert len(snap["waiting_production"]) == 1
    assert len(snap["out_for_delivery"]) == 1
    assert snap["confirmed"][0]["partner"] == "Elshod Market"
    assert snap["confirmed"][0]["items_count"] == 1
    assert snap["confirmed"][0]["overdue"] is False


def test_board_snapshot_overdue_flag(db):
    from app.models.database import Order, Partner
    from app.services.board_service import build_board_snapshot
    p = Partner(name="Kech Market", balance=0, code="P_B2")
    db.add(p); db.flush()
    o = Order(number="AGT-OVD", date=datetime.now(), type="sale", source="agent",
              partner_id=p.id, total=100000, paid=0, debt=100000, status="confirmed",
              delivery_date=date.today() - timedelta(days=1))
    db.add(o); db.commit()
    snap = build_board_snapshot(db)
    assert snap["confirmed"][0]["overdue"] is True


def test_board_snapshot_excludes_pos_and_old_delivered(db):
    from app.models.database import Order, Partner
    from app.services.board_service import build_board_snapshot
    p = Partner(name="P", balance=0, code="P_B3")
    db.add(p); db.flush()
    db.add(Order(number="S-POS", date=datetime.now(), type="sale", source="web",
                 partner_id=p.id, total=50000, paid=50000, debt=0, status="completed"))
    db.commit()
    snap = build_board_snapshot(db)
    total = sum(len(v) for v in snap.values())
    assert total == 0


def test_board_snapshot_delivered_today_vs_yesterday(db):
    from app.models.database import Order, Partner
    from app.services.board_service import build_board_snapshot
    p = Partner(name="Q", balance=0, code="P_B4")
    db.add(p); db.flush()
    db.add(Order(number="AGT-D1", date=datetime.now(), type="sale", source="agent",
                 partner_id=p.id, total=1, paid=1, debt=0, status="delivered",
                 delivery_date=date.today()))
    db.add(Order(number="AGT-D2", date=datetime.now(), type="sale", source="agent",
                 partner_id=p.id, total=1, paid=1, debt=0, status="delivered",
                 delivery_date=date.today() - timedelta(days=1)))
    db.commit()
    snap = build_board_snapshot(db)
    assert len(snap["delivered"]) == 1
    assert snap["delivered"][0]["number"] == "AGT-D1"
