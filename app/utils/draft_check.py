"""Draft hujjat cheklovi — bitta foydalanuvchi bir paytda 1 ta draft.

Per-key konfiguratsiya:
- INV (StockAdjustmentDoc): (user_id, warehouse_id) — har ombor alohida
- HD (ExpenseDoc): (user_id) — bitta admin 1 ta HD
- PUR (Purchase): (user_id) — bitta foydalanuvchi 1 ta PUR
- QLD (Partner/Cash/Employee BalanceDoc): (user_id) — har turi alohida

Bypass: admin/manager ?force_new=1 parametri orqali yangi yarata oladi.
"""
from urllib.parse import quote
from typing import Optional
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session


def find_existing_draft(db: Session, model, **filters):
    """Mavjud draft hujjatni topadi yoki None qaytaradi.
    `status='draft'` avtomatik qo'shiladi."""
    return db.query(model).filter_by(status="draft", **filters).first()


def redirect_to_draft(
    db: Session,
    model,
    edit_url_template: str,
    user_role: str = "",
    force_new: bool = False,
    message: str = "Avval mavjud qoralamani tugating yoki bekor qiling.",
    **filters,
) -> Optional[RedirectResponse]:
    """Mavjud draft bo'lsa edit sahifaga redirect qaytaradi.

    Args:
        db: SQLAlchemy session
        model: Hujjat modeli (StockAdjustmentDoc, ExpenseDoc, ...)
        edit_url_template: URL pattern, "{id}" placeholder bilan
                          (masalan: "/inventory/{id}/edit")
        user_role: current_user.role — admin/manager bypass qila oladi
        force_new: ?force_new=1 parametri (admin uchun)
        message: foydalanuvchiga ko'rsatilgan xabar
        **filters: model bo'yicha filterlar (user_id=..., warehouse_id=...)

    Returns:
        RedirectResponse agar mavjud draft bor — caller darhol qaytarsin
        None agar draft yo'q — caller yangi yaratishga davom etsin
    """
    # Admin/manager force_new bilan bypass qila oladi
    if force_new and (user_role or "").strip().lower() in ("admin", "manager", "menejer"):
        return None

    existing = find_existing_draft(db, model, **filters)
    if not existing:
        return None

    # URL formatlash — placeholder o'rniga real id
    edit_url = edit_url_template.format(id=existing.id)
    sep = "&" if "?" in edit_url else "?"
    full_url = f"{edit_url}{sep}message={quote(message)}"
    return RedirectResponse(url=full_url, status_code=303)
