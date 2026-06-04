"""Hujjat raqami generatori — MAX(number suffix)+1 (H5 race/reuse fix).

Muammo (audit H5):
- `count()+1` — bugungi hujjatlar soniga tayanadi; bittasi O'CHIRILSA son kamayadi
  va raqam TAKRORLANADI (dublikat number).
- `id+1` (global) — prefiks filtrisiz oxirgi yozuv id'siga tayanadi; raqam kunlik
  ketma-ket emas (KK-20260604-1823 kabi) va parallel so'rovlarda dublikat beradi.

Yechim: berilgan prefiks (odatda sana bilan tugaydi, masalan 'DLV-20260604-') uchun
mavjud raqamlardan eng katta suffiksni topib +1 qilish. Izchil, kunlik ketma-ket,
self-healing va o'chirilgan gaplardan ta'sirlanmaydi. Barcha call-site'lar shu
yagona helper'ni ishlatadi (uniform).

Eslatma: bu single-process SQLite'da race oynasini keskin qisqartiradi, lekin
unique-constraint yo'qligida nazariy race butunlay yopilmaydi (kelajak: counter
jadval yoki unique index + retry).
"""
from sqlalchemy.orm import Session


def next_doc_number(
    db: Session,
    model,
    prefix: str,
    *,
    number_attr: str = "number",
    pad: int = 4,
) -> str:
    """`{prefix}{(MAX_suffix+1):0{pad}d}` qaytaradi.

    Args:
        db: DB sessiya.
        model: number ustuniga ega SQLAlchemy model (Payment, CashTransfer, ...).
        prefix: to'liq prefiks, masalan 'KK-20260604-' (oxirgi '-' bilan).
        number_attr: raqam ustuni nomi (default 'number').
        pad: zfill kengligi (default 4).

    Mixed-width suffikslar (ba'zi eski 3-xonali) bo'lsa ham to'g'ri ishlaydi —
    raqamli MAX olinadi (leksik emas).
    """
    col = getattr(model, number_attr)
    rows = db.query(col).filter(col.like(f"{prefix}%")).all()
    max_num = 0
    for row in rows:
        val = row[0]
        if not val:
            continue
        try:
            n = int(str(val).split("-")[-1])
        except (ValueError, IndexError):
            continue
        if n > max_num:
            max_num = n
    return f"{prefix}{str(max_num + 1).zfill(pad)}"
