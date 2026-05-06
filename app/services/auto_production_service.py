"""Stock=0 da agent buyurtma uchun avtomatik production hujjat yaratish.

supervisor_confirm_agent_order chaqirsa: yetishmagan har mahsulot uchun
mos recipe topib, draft Production hujjati yaratadi. Operator
keyinchalik yakunlaydi va Production.operator_id ga yoziladi (piecework
kg avtomat hisoblanadi).
"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.database import Production, Recipe


def auto_create_productions_for_order(
    db: Session, order, shortage_items: list[dict]
) -> list[dict]:
    """shortage_items: [{product_id, name, need, have}] — Stock yetmagan mahsulotlar.

    Qaytaradi: yaratilgan productions ro'yxati [{number, product_name, quantity}].
    Recipe topilmagan mahsulot uchun yaratilmaydi (manual production talab qilinadi).
    """
    if not shortage_items:
        return []

    today = datetime.now()
    prefix = f"PR-{today.strftime('%Y%m%d')}"
    last = (
        db.query(Production)
        .filter(Production.number.like(f"{prefix}%"))
        .order_by(Production.id.desc())
        .first()
    )
    try:
        seq = int(last.number.split("-")[-1]) + 1 if last and last.number else 1
    except (ValueError, IndexError, AttributeError):
        seq = 1

    created = []
    for it in shortage_items:
        product_id = it.get("product_id")
        need = float(it.get("need") or 0)
        if not product_id or need <= 0:
            continue

        # Eng yangi active recipe shu mahsulot uchun
        recipe = (
            db.query(Recipe)
            .filter(Recipe.product_id == product_id, Recipe.is_active == True)
            .order_by(Recipe.id.desc())
            .first()
        )
        if not recipe:
            # Recipe yo'q — auto yaratib bo'lmaydi, operator manual yaratadi
            continue

        production = Production(
            number=f"{prefix}-{seq:03d}",
            date=today,
            recipe_id=recipe.id,
            warehouse_id=recipe.default_warehouse_id,
            output_warehouse_id=recipe.default_output_warehouse_id,
            quantity=need,
            status="draft",
            note=f"Auto: {order.number} (Stock=0). Operator yakunlasin.",
            order_id=order.id,
            current_stage=0,
            max_stage=0,
        )
        db.add(production)
        db.flush()
        created.append({
            "number": production.number,
            "product_name": it.get("name", f"#{product_id}"),
            "quantity": need,
        })
        seq += 1

    return created
