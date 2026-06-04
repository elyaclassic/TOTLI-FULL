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


def test_update_output_anomaly_warns_and_skips(db, caplog):
    # C2 fix (2026-06-04): g'ayritabiiy tannarx (50000 > sotuv 10000) endi YOZILMAYDI
    # (eski 100 saqlanadi) + "PRICE ANOMALY SKIPPED" warning. Eski test "warns but
    # completes" (yozardi) edi — yangi qo'riq overwrite'ni bloklaydi.
    import logging
    from app.routes.production import _update_output_cost_and_price
    p, r = _mk_output(db, pp=100, sale=10000)
    _mk_stock(db, wh_id=1, product_id=p.id)
    with caplog.at_level(logging.WARNING):
        _update_output_cost_and_price(db, 1, r, 50000.0)
    db.refresh(p)
    assert p.purchase_price == 100, "Anomaliya bloklanib, eski tannarx saqlanishi kerak"
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


def test_backfill_recomputes_per_unit_apply(db):
    """Backfill: 400gr SKU retsept dona-narxiga keladi (kg-narx EMAS), idempotent,
    distinct BACKFILL- doc_number, dry-run yozmaydi."""
    import importlib.util
    from pathlib import Path
    from app.models.database import Product, Recipe, RecipeItem, Stock, ProductPriceHistory
    from app.routes.production import _calculate_recipe_cost_per_kg
    from app.utils.production_order import recipe_kg_per_unit

    raw = Product(name="UN", code="UN", type="xom", is_active=True,
                  purchase_price=10000, sale_price=0)
    db.add(raw); db.flush()
    out = Product(name="NON 400gr", code="NON400", type="tayyor", is_active=True,
                  purchase_price=15000, sale_price=20000)
    db.add(out); db.flush()
    r = Recipe(product_id=out.id, name="NON 400gr", output_quantity=1.0, is_active=True)
    db.add(r); db.flush()
    db.add(RecipeItem(recipe_id=r.id, product_id=raw.id, quantity=1.0))
    db.add(Stock(warehouse_id=1, product_id=out.id, quantity=5.0, cost_price=15000))
    db.commit()

    expected = _calculate_recipe_cost_per_kg(db, r.id) * recipe_kg_per_unit(r)
    assert expected > 0 and expected < 15000           # per-unit, buzuq qiymatdan past

    _bf_path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_produced_purchase_price.py"
    spec = importlib.util.spec_from_file_location("bf_mod", str(_bf_path))
    bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)

    # DRY-RUN: yozmaydi
    bf.run(db, apply=False)
    db.refresh(out)
    assert out.purchase_price == 15000
    assert db.query(ProductPriceHistory).count() == 0

    # APPLY
    bf.run(db, apply=True)
    db.refresh(out)
    assert abs(out.purchase_price - expected) < 1e-6
    st = db.query(Stock).filter(Stock.product_id == out.id).first()
    assert abs(st.cost_price - expected) < 1e-6
    hrows = db.query(ProductPriceHistory).all()
    assert len(hrows) == 1
    assert hrows[0].doc_number.startswith("BACKFILL-")

    # Idempotent: 2-marta apply = bir xil, yangi history yo'q (o'zgarmadi)
    bf.run(db, apply=True)
    db.refresh(out)
    assert abs(out.purchase_price - expected) < 1e-6
    assert db.query(ProductPriceHistory).count() == 1


def test_backfill_idempotent_with_semi_chain(db):
    """finished -> semi (semi ham aktiv retseptli) zanjir: 2-marta apply = 0 yangi
    history (two-phase order-independent). Eski interleaved kod bu yerda surilardi."""
    import importlib.util
    from pathlib import Path
    from app.models.database import Product, Recipe, RecipeItem, Stock, ProductPriceHistory

    raw = Product(name="SUT", code="SUT", type="xom", is_active=True,
                   purchase_price=8000, sale_price=0)
    db.add(raw); db.flush()
    semi = Product(name="QIYOM yarim", code="QYM", type="yarim_tayyor", is_active=True,
                   purchase_price=24000, sale_price=0)
    db.add(semi); db.flush()
    fin = Product(name="HOLVA 400gr", code="H400", type="tayyor", is_active=True,
                  purchase_price=24000, sale_price=40000)
    db.add(fin); db.flush()
    rs = Recipe(product_id=semi.id, name="QIYOM yarim", output_quantity=1.0, is_active=True)
    db.add(rs); db.flush()
    db.add(RecipeItem(recipe_id=rs.id, product_id=raw.id, quantity=2.0))
    rf = Recipe(product_id=fin.id, name="HOLVA 400gr", output_quantity=1.0, is_active=True)
    db.add(rf); db.flush()
    db.add(RecipeItem(recipe_id=rf.id, product_id=semi.id, quantity=1.0))
    db.add(Stock(warehouse_id=1, product_id=semi.id, quantity=3.0, cost_price=24000))
    db.add(Stock(warehouse_id=1, product_id=fin.id, quantity=3.0, cost_price=24000))
    db.commit()

    _bf_path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_produced_purchase_price.py"
    spec = importlib.util.spec_from_file_location("bf_mod2", str(_bf_path))
    bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)

    bf.run(db, apply=True)
    n1 = db.query(ProductPriceHistory).count()
    semi_pp1 = db.query(Product).filter(Product.id == semi.id).first().purchase_price
    fin_pp1 = db.query(Product).filter(Product.id == fin.id).first().purchase_price
    assert n1 >= 2  # semi + finished tuzatildi

    bf.run(db, apply=True)   # 2-marta
    n2 = db.query(ProductPriceHistory).count()
    assert n2 == n1          # 0 YANGI history (idempotent)
    assert db.query(Product).filter(Product.id == semi.id).first().purchase_price == semi_pp1
    assert db.query(Product).filter(Product.id == fin.id).first().purchase_price == fin_pp1


def test_backfill_fixed_point_multilevel_tayyor_chain(db):
    """FIN -> MID(type='tayyor', o'z aktiv retsepti bor) -> raw.
    (a) BITTA apply FIN ni ham MID ni ham to'g'rilaydi (own fixed-point bir o'tishda);
    (b) 2-apply = 0 yangi history, narxlar o'zgarmaydi (idempotent)."""
    import importlib.util
    from pathlib import Path
    from app.models.database import Product, Recipe, RecipeItem, Stock, ProductPriceHistory

    raw = Product(name="MOY", code="MOY", type="xom", is_active=True,
                   purchase_price=5000, sale_price=0)
    db.add(raw); db.flush()
    mid = Product(name="ARALASHMA", code="ARL", type="tayyor", is_active=True,
                   purchase_price=15000, sale_price=0)
    db.add(mid); db.flush()
    fin = Product(name="TORT 1kg", code="T1", type="tayyor", is_active=True,
                   purchase_price=42000, sale_price=80000)
    db.add(fin); db.flush()
    r_mid = Recipe(product_id=mid.id, name="ARALASHMA 1kg", output_quantity=1.0, is_active=True)
    db.add(r_mid); db.flush()
    db.add(RecipeItem(recipe_id=r_mid.id, product_id=raw.id, quantity=2.0))  # 2*5000
    r_fin = Recipe(product_id=fin.id, name="TORT 1kg", output_quantity=1.0, is_active=True)
    db.add(r_fin); db.flush()
    db.add(RecipeItem(recipe_id=r_fin.id, product_id=mid.id, quantity=3.0))  # 3 * MID_cost
    db.add(Stock(warehouse_id=1, product_id=mid.id, quantity=4.0, cost_price=15000))
    db.add(Stock(warehouse_id=1, product_id=fin.id, quantity=4.0, cost_price=42000))
    db.commit()

    _bf = Path(__file__).resolve().parents[1] / "scripts" / "backfill_produced_purchase_price.py"
    spec = importlib.util.spec_from_file_location("bf_fp", str(_bf))
    bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)

    bf.run(db, apply=True)
    db.refresh(mid); db.refresh(fin)
    # MID 1kg: raw(no recipe)=5000, 2*5000=10000, kg/unit("ARALASHMA 1kg")=1.0 -> 10000
    assert abs(mid.purchase_price - 10000.0) < 1e-6
    # FIN 1kg: MID recursed (NOT stored 999999) per-kg=10000, 3*10000=30000, kg/unit=1.0 -> 30000
    assert abs(fin.purchase_price - 30000.0) < 1e-6, f"FIN bir o'tishda tuzalmadi: {fin.purchase_price}"
    n1 = db.query(ProductPriceHistory).count()

    bf.run(db, apply=True)  # 2-marta
    db.refresh(mid); db.refresh(fin)
    assert db.query(ProductPriceHistory).count() == n1   # 0 yangi (idempotent)
    assert abs(mid.purchase_price - 10000.0) < 1e-6
    assert abs(fin.purchase_price - 30000.0) < 1e-6


def test_backfill_converges_with_live_cost_per_unit_dona_400gr(db):
    """C2 (to'g'rilangan): "dona"-birlik 400gr SKU (real 130 SKU shu yo'lda) uchun
    backfill `new` == jonli forward-fix cost_per_unit AYNAN. C1 (yakuniy review)
    rad etilgan; bu doimiy konvergensiya fence'i."""
    import importlib.util
    from pathlib import Path
    from app.models.database import Product, Recipe, RecipeItem, Stock, Production, Unit
    from app.routes.production import _calculate_total_material_cost
    from app.utils.production_order import recipe_kg_per_unit, production_output_quantity_for_stock

    dona = Unit(name="dona")          # ADAPT to real Unit model (add code= if column exists)
    db.add(dona); db.flush()
    raw1 = Product(name="PISTA xom", code="PX", type="xom", is_active=True,
                    purchase_price=42000, sale_price=0)
    raw2 = Product(name="SHAKAR xom", code="SX", type="xom", is_active=True,
                    purchase_price=9000, sale_price=0)
    db.add_all([raw1, raw2]); db.flush()
    out = Product(name="MAYDA PISTA 400gr", code="MP400", type="tayyor", is_active=True,
                  purchase_price=999999, sale_price=30000, unit_id=dona.id)
    db.add(out); db.flush()
    r = Recipe(product_id=out.id, name="MAYDA PISTA 400gr", output_quantity=1.0, is_active=True)
    db.add(r); db.flush()
    db.add(RecipeItem(recipe_id=r.id, product_id=raw1.id, quantity=0.3))
    db.add(RecipeItem(recipe_id=r.id, product_id=raw2.id, quantity=0.1))
    db.add(Stock(warehouse_id=1, product_id=out.id, quantity=5.0, cost_price=999999))
    db.commit()

    assert recipe_kg_per_unit(r) == 0.4                       # 400gr, kg/unit != 1.0
    db.refresh(out)
    assert "dona" in ((out.unit.name or "") + " " + (getattr(out.unit, "code", "") or "")).lower()

    prod = Production(number="PR-CONV-002", recipe_id=r.id, quantity=10.0,
                      status="completed", warehouse_id=1)
    db.add(prod); db.flush()
    items = [(it.product_id, float(it.quantity or 0) * float(prod.quantity or 0)) for it in r.items]
    tmc = _calculate_total_material_cost(db, items)
    ou = production_output_quantity_for_stock(db, prod, r)    # dona -> prod.quantity (=10)
    live_cpu = tmc / ou if ou else 0.0
    assert live_cpu > 0

    _bf = Path(__file__).resolve().parents[1] / "scripts" / "backfill_produced_purchase_price.py"
    spec = importlib.util.spec_from_file_location("bf_conv2", str(_bf))
    bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)
    report = bf.run(db, apply=False)
    row = [x for x in report if x[0] == out.id]
    assert row, "out report'da yo'q"
    backfill_new = row[0][3]

    assert abs(backfill_new - live_cpu) < 1e-6, (
        f"DIVERGENSIYA: backfill={backfill_new} live_cpu={live_cpu} "
        f"unit=dona kg/unit={recipe_kg_per_unit(r)}")
    db.refresh(out)
    assert out.purchase_price == 999999          # DRY-RUN yozmadi


def test_backfill_skips_suspect_rows(db):
    """SUSPECT(>70%) qatorlar --apply'da YOZILMAYDI (to'liqsiz retsept jonli
    ma'lumotni buzmasin). flag=='' bo'lgan toza qatorlargina yoziladi."""
    import importlib.util
    from pathlib import Path
    from app.models.database import Product, Recipe, RecipeItem, Stock, ProductPriceHistory

    raw = Product(name="ARZON xom", code="AZ", type="xom", is_active=True,
                   purchase_price=1000, sale_price=0)
    db.add(raw); db.flush()
    out = Product(name="SHUBHALI MAHSULOT", code="SUSP", type="tayyor", is_active=True,
                  purchase_price=100000, sale_price=200000)   # old=100000
    db.add(out); db.flush()
    r = Recipe(product_id=out.id, name="SHUBHALI MAHSULOT", output_quantity=1.0, is_active=True)
    db.add(r); db.flush()
    db.add(RecipeItem(recipe_id=r.id, product_id=raw.id, quantity=0.1))  # new ~100, -99.9%
    db.add(Stock(warehouse_id=1, product_id=out.id, quantity=5.0, cost_price=100000))
    db.commit()

    _bf = Path(__file__).resolve().parents[1] / "scripts" / "backfill_produced_purchase_price.py"
    spec = importlib.util.spec_from_file_location("bf_susp", str(_bf))
    bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)

    rep = bf.run(db, apply=True)
    row = [x for x in rep if x[0] == out.id][0]
    assert row[4].startswith("SUSPECT"), f"SUSPECT kutilgandi: {row}"
    db.refresh(out)
    assert out.purchase_price == 100000          # YOZILMADI (eski qiymat saqlandi)
    assert db.query(ProductPriceHistory).filter(
        ProductPriceHistory.product_id == out.id).count() == 0
