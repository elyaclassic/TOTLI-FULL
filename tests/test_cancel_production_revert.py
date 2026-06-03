"""C3: completed production'ni bekor qilganda stock teskari qaytarilishi kerak.

_cancel_production_with_revert helperi:
- draft  -> faqat status='cancelled', stock harakati yo'q
- completed (yetarli output stock) -> stock qaytariladi (production_revert), status='cancelled'
- completed (output yetishmaydi)   -> xato xabar, status o'zgarmaydi (qisman zarar yo'q)
"""
from app.models.database import (
    Unit, Product, Warehouse, Stock, Recipe, RecipeItem,
    Production, ProductionItem, StockMovement,
)


def _setup_completed_production(db, output_qty=10.0, stock_qty=10.0):
    """Yakunlangan production + yetarli output stock yaratadi.

    Output mahsulot birligi 'Dona' (dona) -> output_units == production.quantity.
    """
    unit = Unit(code="dona", name="Dona")
    db.add(unit)
    db.flush()

    out_product = Product(name="Tayyor mahsulot", unit_id=unit.id, purchase_price=5000)
    raw_product = Product(name="Xom ashyo", unit_id=unit.id, purchase_price=1000)
    db.add_all([out_product, raw_product])
    db.flush()

    raw_wh = Warehouse(name="Xom ombor", code="RAW-WH")
    out_wh = Warehouse(name="Tayyor ombor", code="OUT-WH")
    db.add_all([raw_wh, out_wh])
    db.flush()

    recipe = Recipe(product_id=out_product.id, name="Test retsept", output_quantity=1)
    db.add(recipe)
    db.flush()
    db.add(RecipeItem(recipe_id=recipe.id, product_id=raw_product.id, quantity=2))
    db.flush()

    prod = Production(
        number="PR-TEST-001",
        recipe_id=recipe.id,
        warehouse_id=raw_wh.id,
        output_warehouse_id=out_wh.id,
        quantity=output_qty,
        status="completed",
    )
    db.add(prod)
    db.flush()
    # production_items: shu buyurtma uchun aniq xom ashyo miqdori
    db.add(ProductionItem(production_id=prod.id, product_id=raw_product.id, quantity=2 * output_qty))
    db.flush()

    # Output mahsulot tayyor omborda mavjud (revert uchun)
    if stock_qty is not None:
        db.add(Stock(warehouse_id=out_wh.id, product_id=out_product.id, quantity=stock_qty))
        db.flush()

    return prod


def _revert_movements(db, prod):
    return db.query(StockMovement).filter(
        StockMovement.document_type == "Production",
        StockMovement.document_id == prod.id,
        StockMovement.operation_type == "production_revert",
    ).all()


def test_cancel_draft_no_revert(db):
    """draft production -> status='cancelled', revert harakati yaratilmaydi, None qaytaradi."""
    from app.routes.production import _cancel_production_with_revert

    prod = _setup_completed_production(db)
    prod.status = "draft"
    db.flush()

    err = _cancel_production_with_revert(db, prod)

    assert err is None
    assert prod.status == "cancelled"
    assert _revert_movements(db, prod) == []


def test_cancel_completed_reverses_stock(db):
    """completed + yetarli output stock -> revert harakati bor, status='cancelled', None."""
    from app.routes.production import _cancel_production_with_revert

    prod = _setup_completed_production(db, output_qty=10.0, stock_qty=10.0)

    err = _cancel_production_with_revert(db, prod)

    assert err is None
    assert prod.status == "cancelled"
    moves = _revert_movements(db, prod)
    assert len(moves) >= 1
    # output uchun manfiy harakat bo'lishi kerak
    assert any(m.quantity_change < 0 for m in moves)


def test_cancel_completed_insufficient_output_blocks(db):
    """completed lekin output sotilgan (yetishmaydi) -> xato string, status o'zgarmaydi."""
    from app.routes.production import _cancel_production_with_revert

    # output_qty=10 kerak, lekin omborda atigi 1 dona bor
    prod = _setup_completed_production(db, output_qty=10.0, stock_qty=1.0)

    err = _cancel_production_with_revert(db, prod)

    assert isinstance(err, str) and err
    assert prod.status == "completed"
    # qisman zarar yo'q: revert harakati yaratilmagan
    assert _revert_movements(db, prod) == []
