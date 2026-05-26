"""Global cmd-palette qidiruv endpoint — Ctrl+K modal uchun."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import (
    get_db, User, Product, Partner, Order, Agent, Employee, Production,
)
from app.deps import require_auth

router = APIRouter(prefix="/api", tags=["api-search"])

LIMIT_PER_CATEGORY = 5
MIN_QUERY_LEN = 2


@router.get("/search")
async def global_search(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Cmd palette uchun multi-domain qidiruv.
    Response: {"categories": [{"name", "icon", "items": [{"id","label","sub","url"}]}]}
    """
    term = (q or "").strip()
    if len(term) < MIN_QUERY_LEN:
        return {"categories": []}

    pattern = f"%{term}%"
    categories = []

    # Mahsulotlar — name yoki code/barcode bo'yicha
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            or_(
                Product.name.ilike(pattern),
                Product.code.ilike(pattern) if hasattr(Product, "code") else Product.name.ilike(pattern),
            ),
        )
        .order_by(Product.name)
        .limit(LIMIT_PER_CATEGORY)
        .all()
    )
    if products:
        categories.append({
            "name": "Mahsulotlar",
            "icon": "bi-box-seam",
            "items": [
                {
                    "id": p.id,
                    "label": p.name,
                    "sub": (getattr(p, "code", None) or "") or (getattr(p, "type", "") or ""),
                    "url": f"/products/{p.id}",
                }
                for p in products
            ],
        })

    # Mijozlar — name yoki phone
    partners = (
        db.query(Partner)
        .filter(
            Partner.is_active == True,
            or_(
                Partner.name.ilike(pattern),
                Partner.phone.ilike(pattern),
            ),
        )
        .order_by(Partner.name)
        .limit(LIMIT_PER_CATEGORY)
        .all()
    )
    if partners:
        categories.append({
            "name": "Mijozlar",
            "icon": "bi-people",
            "items": [
                {
                    "id": pn.id,
                    "label": pn.name,
                    "sub": (pn.phone or "") + (" · " + pn.address if pn.address else ""),
                    "url": f"/partners/detail/{pn.id}",
                }
                for pn in partners
            ],
        })

    # Buyurtmalar/Sotuvlar — Order.number
    orders = (
        db.query(Order)
        .filter(Order.number.ilike(pattern))
        .order_by(Order.id.desc())
        .limit(LIMIT_PER_CATEGORY)
        .all()
    )
    if orders:
        categories.append({
            "name": "Buyurtmalar",
            "icon": "bi-cart-check",
            "items": [
                {
                    "id": o.id,
                    "label": o.number,
                    "sub": f"{o.type or '-'} · {o.status or '-'} · {(o.total or 0):,.0f} so'm".replace(",", " "),
                    "url": f"/sales/edit/{o.id}",
                }
                for o in orders
            ],
        })

    # Productionlar — PR-NNNN
    productions = (
        db.query(Production)
        .filter(Production.number.ilike(pattern))
        .order_by(Production.id.desc())
        .limit(LIMIT_PER_CATEGORY)
        .all()
    )
    if productions:
        categories.append({
            "name": "Ishlab chiqarish",
            "icon": "bi-gear",
            "items": [
                {
                    "id": pr.id,
                    "label": pr.number,
                    "sub": f"{(pr.recipe.name if pr.recipe else '-')} · {pr.status or '-'}",
                    "url": f"/production/orders?q={pr.number}",
                }
                for pr in productions
            ],
        })

    # Agentlar — full_name yoki code
    agents = (
        db.query(Agent)
        .filter(
            Agent.is_active == True,
            or_(
                Agent.full_name.ilike(pattern),
                Agent.code.ilike(pattern) if hasattr(Agent, "code") else Agent.full_name.ilike(pattern),
            ),
        )
        .limit(LIMIT_PER_CATEGORY)
        .all()
    )
    if agents:
        categories.append({
            "name": "Agentlar",
            "icon": "bi-person-badge",
            "items": [
                {
                    "id": a.id,
                    "label": a.full_name,
                    "sub": (getattr(a, "code", None) or "") + (" · " + (a.phone or "") if a.phone else ""),
                    "url": f"/agents/{a.id}",
                }
                for a in agents
            ],
        })

    # Xodimlar — full_name
    employees = (
        db.query(Employee)
        .filter(
            Employee.is_active == True,
            Employee.full_name.ilike(pattern),
        )
        .limit(LIMIT_PER_CATEGORY)
        .all()
    )
    if employees:
        categories.append({
            "name": "Xodimlar",
            "icon": "bi-person-workspace",
            "items": [
                {
                    "id": e.id,
                    "label": e.full_name,
                    "sub": (getattr(e, "phone", None) or ""),
                    "url": f"/employees/edit/{e.id}",
                }
                for e in employees
            ],
        })

    return {"categories": categories, "query": term}
