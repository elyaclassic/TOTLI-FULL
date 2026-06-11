"""Agent buyurtma merge — subtotal regressiya testi.

Bug (2026-06-11): agent o'z buyurtmasiga yangi qator qo'shganda, mavjud bugungi
draft buyurtmaga "merge" qilinadi. Yangi qator db.add() bilan FK orqali
qo'shilardi, lekin existing_order.items relationship collection'iga
append qilinmasdi → new_subtotal stale collection'dan hisoblanib, yangi qator
subtotalga kirmasdi (masalan #1554: ZEBRA qatori tushib qolgan, 280k farq).
"""
import asyncio


class _FakeReq:
    """Minimal Request — agent_create_order faqat .json() va .headers ishlatadi."""
    def __init__(self, body):
        self._body = body
        self.headers = {}

    async def json(self):
        return self._body


def _call_create(body, db):
    from app.routes.api_agent_ops import agent_create_order
    return asyncio.run(agent_create_order(_FakeReq(body), db))


def _setup_agent_world(db):
    from app.models.database import Agent, Partner, Product, Warehouse, ProductPrice, User
    from app.utils.auth import hash_password
    u = User(username="ag_test", password_hash=hash_password("x"),
             full_name="Agent Test", role="agent", is_active=True)
    db.add(u); db.flush()
    ag = Agent(code="AG-MERGE", full_name="Agent Test", phone="+998900000777",
               user_id=u.id, is_active=True)
    db.add(ag); db.flush()
    partner = Partner(name="Merge Klient", is_active=True, agent_id=ag.id, price_type_id=4)
    db.add(partner); db.flush()
    wh = Warehouse(name="Tayyor mahsulot ombori", code="WH-TM", is_active=True)
    db.add(wh); db.flush()
    prods = []
    for i, (nm, pr) in enumerate([("P1", 100000), ("P2", 200000), ("P3", 300000)]):
        p = Product(name=nm, code=f"PRM{i}", is_active=True, is_for_agent=True)
        db.add(p); db.flush()
        db.add(ProductPrice(product_id=p.id, price_type_id=4, sale_price=pr))
        prods.append(p)
    db.commit()
    return ag, partner, prods


def test_agent_merge_recomputes_subtotal_with_new_item(db):
    """Mavjud draft buyurtmaga YANGI qator merge bo'lganda subtotal to'liq bo'lsin."""
    from app.utils.auth import create_session_token
    from app.models.database import Order, OrderItem
    ag, partner, prods = _setup_agent_world(db)
    tok = create_session_token(ag.id, "agent")

    # 1-buyurtma: P1 + P2  (subtotal = 100k + 200k = 300k)
    r1 = _call_create({
        "token": tok, "partner_id": partner.id,
        "items": [{"product_id": prods[0].id, "qty": 1},
                  {"product_id": prods[1].id, "qty": 1}],
    }, db)
    assert r1.get("success"), r1

    # 2-buyurtma: P3 (yangi qator) — shu kunlik draftga MERGE bo'ladi
    r2 = _call_create({
        "token": tok, "partner_id": partner.id,
        "items": [{"product_id": prods[2].id, "qty": 1}],
    }, db)
    assert r2.get("success"), r2
    oid = r2["order_id"]

    # Tekshiruv: subtotal == 3 qator yig'indisi (100k+200k+300k = 600k)
    db.expire_all()
    items = db.query(OrderItem).filter(OrderItem.order_id == oid).all()
    isum = sum((it.quantity or 0) * (it.price or 0) for it in items)
    o = db.query(Order).get(oid)
    assert len(items) == 3, f"3 qator kutilgan, topildi {len(items)}"
    assert abs((o.subtotal or 0) - isum) < 1, \
        f"subtotal={o.subtotal} != qatorlar yig'indisi={isum} (merge yangi qatorni o'tkazib yubordi)"
    assert abs((o.total or 0) - isum) < 1, f"total={o.total} != {isum} (chegirmasiz)"
