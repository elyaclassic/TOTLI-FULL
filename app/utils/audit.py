"""
Audit log — barcha muhim operatsiyalar tarixi.
Kim, qachon, nima qilgani saqlanadi.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.database import AuditLog


def log_action(
    db: Session,
    user=None,
    action: str = "",
    entity_type: str = "",
    entity_id: int = None,
    entity_number: str = None,
    details: str = None,
    ip_address: str = None,
):
    """Audit logga yozuv qo'shish."""
    entry = AuditLog(
        timestamp=datetime.now(),
        user_id=user.id if user else None,
        user_name=(getattr(user, "full_name", None) or getattr(user, "username", None) or "") if user else "",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_number=entity_number or "",
        details=details or "",
        ip_address=ip_address or "",
    )
    db.add(entry)
    # commit qilmaymiz — chaqiruvchi o'zi commit qiladi
