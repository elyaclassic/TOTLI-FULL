"""Partner credit limit enforcement.

Mijozning `credit_limit` (kredit chegarasi) ni tekshiradi. Yangi qarz buyurtma
yaratayotganda partner.balance + new_debt > credit_limit bo'lsa rad etiladi.

Konvensiya:
- credit_limit == 0 → "limit yo'q" (chakana xaridor uchun)
- credit_limit > 0 → faqat shu summagacha qarzga olishi mumkin
- naqd to'lov (order.debt == 0) tekshiruvga tushmaydi
"""
from typing import Optional

from app.models.database import Partner


def check_credit_limit(partner: Optional[Partner], new_debt: float) -> tuple[bool, str]:
    """Mijoz qarz limitini tekshiradi.

    Args:
        partner: Partner obyekti (None bo'lsa skip)
        new_debt: Yangi buyurtmadan kelib chiqadigan qo'shimcha qarz miqdori (so'm)

    Returns:
        (allowed: bool, error_message: str)
        allowed=True → buyurtmani davom ettirish mumkin
        allowed=False → error_message bilan rad etish
    """
    if not partner:
        return True, ""
    if new_debt <= 0:
        # Naqd yoki qarzsiz — limit tekshirilmaydi
        return True, ""
    limit = float(partner.credit_limit or 0)
    if limit <= 0:
        # 0 yoki manfiy → limit yo'q (chakana xaridor)
        return True, ""
    current_balance = float(partner.balance or 0)
    projected_balance = current_balance + new_debt
    if projected_balance > limit:
        return False, (
            f"Mijoz \"{partner.name}\" kredit limitidan oshib ketdi: "
            f"hozirgi qarz {current_balance:,.0f} + yangi {new_debt:,.0f} = "
            f"{projected_balance:,.0f} so'm, limit {limit:,.0f} so'm"
        )
    return True, ""
