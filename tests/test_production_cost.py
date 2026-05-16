from datetime import datetime

from app.models.database import Product, Recipe, RecipeItem, Stock


def _mk_output(db, *, name="MAYDA PISTA 400gr", pp=999999, sale=20000):
    p = Product(name=name, code=name.replace(" ", "_"), type="tayyor",
                is_active=True, purchase_price=pp, sale_price=sale)
    db.add(p); db.flush()
    r = Recipe(product_id=p.id, name=name, output_quantity=1.0, is_active=True)
    db.add(r); db.flush()
    return p, r


def _mk_stock(db, *, wh_id, product_id, qty=10.0, cost=999999):
    s = Stock(warehouse_id=wh_id, product_id=product_id, quantity=qty, cost_price=cost)
    db.add(s); db.commit()
    return s


def test_update_output_sets_pp_to_cost_per_unit_not_weighted(db):
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=999999)
    _mk_stock(db, wh_id=1, product_id=p.id, qty=10.0, cost=999999)
    _update_output_cost_and_price(db, 1, r, 15000.0)
    db.refresh(p)
    assert p.purchase_price == 15000.0


def test_update_output_same_cost_no_duplicate(db):
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=999999)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0)
    _update_output_cost_and_price(db, 1, r, 15000.0)
    db.refresh(p)
    assert p.purchase_price == 15000.0


def test_update_output_zero_cost_keeps_old(db):
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=12345)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 0.0)
    db.refresh(p)
    assert p.purchase_price == 12345


def test_update_output_writes_price_history(db):
    from app.routes.production import _update_output_cost_and_price
    from app.models.database import ProductPriceHistory
    p, r = _mk_output(db, pp=999999)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0)
    rows = db.query(ProductPriceHistory).filter(ProductPriceHistory.product_id == p.id).all()
    assert len(rows) == 1
    assert rows[0].old_purchase_price == 999999.0
    assert rows[0].new_purchase_price == 15000.0
    assert rows[0].doc_number.startswith("PRC-")


def test_update_output_no_history_when_unchanged(db):
    from app.routes.production import _update_output_cost_and_price
    from app.models.database import ProductPriceHistory
    p, r = _mk_output(db, pp=15000)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0)
    assert db.query(ProductPriceHistory).filter(
        ProductPriceHistory.product_id == p.id).count() == 0


def test_update_output_anomaly_warns_but_completes(db, caplog):
    import logging
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=100, sale=10000)
    _mk_stock(db, wh_id=1, product_id=p.id)
    with caplog.at_level(logging.WARNING):
        _update_output_cost_and_price(db, 1, r, 50000.0)
    db.refresh(p)
    assert p.purchase_price == 50000.0
    assert any("PRICE ANOMALY" in m for m in caplog.messages)


def test_update_output_reconfirm_changed_cost_two_history_no_error(db):
    """Bekor→qayta-tasdiq o'zgargan tannarx bilan: 2 history, distinct doc_number,
    IntegrityError YO'Q (eski spec bu yerda UNIQUE buzilardi)."""
    from app.routes.production import _update_output_cost_and_price
    from app.models.database import ProductPriceHistory
    p, r = _mk_output(db, pp=999999)
    _mk_stock(db, wh_id=1, product_id=p.id)
    _update_output_cost_and_price(db, 1, r, 15000.0)
    _update_output_cost_and_price(db, 1, r, 18000.0)   # turli cost (re-confirm)
    db.commit()                                         # UNIQUE buzilsa shu yerda portlardi
    db.refresh(p)
    assert p.purchase_price == 18000.0
    rows = (db.query(ProductPriceHistory)
              .filter(ProductPriceHistory.product_id == p.id)
              .order_by(ProductPriceHistory.id).all())
    assert len(rows) == 2
    assert rows[0].new_purchase_price == 15000.0
    assert rows[1].new_purchase_price == 18000.0
    assert rows[0].doc_number != rows[1].doc_number
    assert all(x.doc_number.startswith("PRC-") for x in rows)


def test_bulk_confirm_same_transaction_distinct_doc_numbers(db):
    """Bir tranzaksiyada ketma-ket 3 mahsulot (bulk-confirm) -> har biri distinct
    PRC- doc_number, IntegrityError YO'Q. _update_output_cost_and_price ichidagi
    db.flush() pending PRC- qatorni keyingi SELECT-max'ga ko'rsatishini fence qiladi."""
    from app.routes.production import _update_output_cost_and_price
    from app.models.database import ProductPriceHistory

    triples = []
    for i in range(3):
        p, r = _mk_output(db, name=f"BULK PROD {i}", pp=999999)
        _mk_stock(db, wh_id=1, product_id=p.id)
        triples.append((p, r, 10000.0 + i * 1000))

    for p, r, cost in triples:          # bir tranzaksiya, commit YO'Q
        _update_output_cost_and_price(db, 1, r, cost)
    db.commit()                          # flush noto'g'ri bo'lsa shu yerda IntegrityError

    docs = [row.doc_number for row in db.query(ProductPriceHistory).all()]
    assert len(docs) == 3
    assert len(set(docs)) == 3           # uchchalasi distinct
    assert all(d.startswith("PRC-") for d in docs)
    for p, r, cost in triples:
        db.refresh(p)
        assert p.purchase_price == cost
