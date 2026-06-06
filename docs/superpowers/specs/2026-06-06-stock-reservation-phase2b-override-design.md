# Stock Reservation Faza 2-B: Admin/Manager Override — Dizayn

**Sana:** 2026-06-06
**Holat:** Tasdiqlangan dizayn → plan
**Bog'liq:** [[project-stock-reservation-deployed-20260606]] (Faza 1 + 2-A + 2-C)

---

## 1. Muammo

Faza 1 (sotuv) va 2-A (transfer) band qilingan mahsulotni **qattiq bloklaydi**. Ba'zan admin/manager bilib turib band ustidan o'tishi kerak (masalan: agent buyurtma baribir bekor bo'ladi, yoki shoshilinch POS mijoz). Hozir buning iloji yo'q — band buyurtma dispatch/bekor bo'lguncha kutish kerak.

## 2. Maqsad

Admin/manager band tufayli bloklangan **transfer** va **POS sotuv**ni "baribir o'tkaz" (force) qila olsin — javobgarlik audit log bilan saqlanadi.

**Qabul qilingan qarorlar (foydalanuvchi 2026-06-06):**
- Doira = transfer + POS sotuv. (Konversiya/employee keyin.)
- Ruxsat = admin + manager.

## 3. Mexanizm (yagona naqsh)

### 3.1. Yangi helper: `app/services/stock_reservation.py`
```python
def reservation_override(current_user, force) -> bool:
    """force truthy VA role admin/manager bo'lsa True (band e'tiborga olinmaydi)."""
    if not force:
        return False
    role = getattr(current_user, "role", None) if current_user else None
    return role in ("admin", "manager", "menejer")
```

### 3.2. Har band darvozasida
- `force` param request'dan olinadi (Form/Query, masalan `force: int = 0` yoki `force: str = None`).
- `override = reservation_override(current_user, force)`.
- `reserved = 0.0 if override else get_reserved_quantity(db, wh, pid)` (yoki get_available_stock o'rniga shartli).
- **Audit:** `override` aktiv VA haqiqiy band (`get_reserved_quantity > 1e-6`) bo'lganda — `AuditLog(action="reservation_override", entity_type=..., entity_number=doc, details="reserved=X bypassed by <user>")`.

## 4. Darvozalar (force param + override)

| Fayl:funksiya | Hozir (Faza 1/2-A) |
|---------------|--------------------|
| `warehouse.py` transfer confirm | `get_available_stock_at_date(...)` |
| `warehouse.py` movement | `source.quantity − get_reserved_quantity(...)` |
| `sales.py` sales_confirm (POS) | `get_available_stock(...)` |
| `sales.py` POS quick-sale | `source.quantity − get_reserved_quantity(...)` |
| `sales.py` /pos/complete | `source.quantity − get_reserved_quantity(...)` |

Har birida `reserved` hisoblash override bo'lsa 0 ga aylanadi (band chetlab o'tiladi).

## 5. UX

- **Transfer sahifalari** (server-rendered, error redirect): band tufayli xato bo'lsa, sahifada admin/manager uchun **"⚠️ Band — baribir o'tkaz"** tugmasi (formani `force=1` bilan qayta yuboradi). Faqat `current_user.role in (admin, manager)` ko'radi.
- **POS** (JSON javob): band xatosi javobiga `reserved_block: true` qo'shiladi. POS JS band xatosini ko'rsatganda admin/manager uchun "Baribir sotish" tasdig'i → `force=1` bilan qayta yuboradi.

## 6. Edge case
- `force` bor, lekin role admin/manager EMAS → override yo'q (band saqlanadi). Xavfsiz.
- `force` bor, lekin band yo'q → oddiy o'tadi, audit log YOZILMAYDI (shovqin yo'q).
- Override bo'lsa ham jismoniy stock yetmasa → baribir bloklanadi (override faqat band'ni chetlab o'tadi, manfiy jismoniy stock'ni emas).
- `.with_for_update()` lock (POS quick-sale, /pos/complete, konversiya) SAQLANADI.

## 7. Test strategiyasi
- `reservation_override`: force+admin→True; force+manager→True; force+sotuvchi→False; force yo'q→False.
- Gate logikasi: override bo'lsa band band qqilingan mahsulot o'tadi; override yo'q bo'lsa bloklanadi (Faza 1/2-A regressiya saqlanadi).

## 8. Doiradan tashqari
- Konversiya va employee mahsulot xaridi override (keyin, agar so'ralsa).
- Override limiti/tasdiq oqimi (hozir oddiy force).

## 9. Risk
- **Ma'lumotga ta'sir:** Yo'q (override faqat band tekshiruvini shartli qiladi).
- **Xulq:** admin/manager band ustidan o'ta oladi — maqsadli, audit bilan. Boshqalar uchun o'zgarish yo'q.
- **Tier:** B (xulq qo'shiladi, lekin faqat admin/manager + force bilan). Deploy: restart.
