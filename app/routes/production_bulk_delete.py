"""
Ishlab chiqarish buyurtmalari — bulk-delete (main.py da birinchi include qilinadi, 404 bo'lmasligi uchun).
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import quote

from app.models.database import get_db, Production, Stock, StockMovement, User
from app.deps import require_admin

router = APIRouter(prefix="/production", tags=["production-bulk-delete"])


@router.get("/orders/bulk-delete")
@router.get("/orders/bulk_delete")
def bulk_delete_get():
    return RedirectResponse(url="/production/orders", status_code=302)


@router.post("/orders/bulk-delete")
@router.post("/orders/bulk_delete")
async def bulk_delete_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    form = await request.form()
    raw_ids = form.getlist("prod_ids")
    prod_ids = [int(x) for x in raw_ids if str(x).strip().isdigit()]
    if not prod_ids:
        return RedirectResponse(
            url="/production/orders?error=delete&detail=" + quote("Hech qaysi buyurtma tanlanmagan."),
            status_code=303,
        )
    not_deletable = []
    for pid in prod_ids:
        production = db.query(Production).filter(Production.id == pid).first()
        if production and production.status not in ("draft", "cancelled"):
            not_deletable.append(production.number or str(pid))
    if not_deletable:
        return RedirectResponse(
            url="/production/orders?error=delete&detail=" + quote(
                "Tasdiqlangan yoki jarayondagi buyurtmalarni o'chirish mumkin emas. Avval «Tasdiqlashni bekor qilish» bosing. Masalan: " + ", ".join(not_deletable[:3]) + ("..." if len(not_deletable) > 3 else "")
            ),
            status_code=303,
        )
    deleted = 0
    for pid in prod_ids:
        production = db.query(Production).filter(Production.id == pid).first()
        if not production:
            continue
        movements = db.query(StockMovement).filter(
            StockMovement.document_type == "Production",
            StockMovement.document_id == pid,
        ).all()
        for m in movements:
            stock = db.query(Stock).filter(
                Stock.warehouse_id == m.warehouse_id,
                Stock.product_id == m.product_id,
            ).first()
            if stock:
                stock.quantity = (stock.quantity or 0) - (m.quantity_change or 0)
            db.delete(m)
        db.delete(production)
        deleted += 1
    db.commit()
    return RedirectResponse(url="/production/orders?bulk_deleted=" + str(deleted), status_code=303)
