# Stock Reservation Faza 2-C: Reservation UI (Qoldiq hisoboti) — Dizayn

**Sana:** 2026-06-06
**Holat:** Tasdiqlangan dizayn → plan
**Bog'liq:** [[project-stock-reservation-deployed-20260606]] (Faza 1 + 2-A)

---

## 1. Muammo

Faza 1 (sotuv) va 2-A (transfer) band qilingan mahsulotni bloklaydi, lekin **ko'rinmas** — operator "nega bloklandi?" deb hayron bo'ladi. Band miqdor hech qayerda ko'rinmaydi.

## 2. Maqsad

`/reports/stock` (Qoldiq hisoboti) jadvaliga **Band** va **Erkin** ustunlarini qo'shish → operator har mahsulot uchun jismoniy qoldiq, band (waiting_production), va erkin (sotish/transfer mumkin) miqdorni ko'rsin.

**Qabul qilingan qarorlar (foydalanuvchi 2026-06-06):**
- Doira = faqat Qoldiq hisoboti (/reports/stock). Boshqa ekranlar keyin.
- Band = hozirgi tushuncha → faqat joriy ko'rinishda (sana-filtrisiz).

## 3. Yondashuv

Faza 1 reservation mantig'idan foydalanish. Performance uchun yangi **batch helper** `get_all_reservations(db)` → barcha `waiting_production` band miqdorlarini BITTA query bilan {(wh,pid): qty} dict qaytaradi (har qatorga alohida query emas).

## 4. Komponentlar

### 4.1. Yangi helper: `app/services/stock_reservation.py`
```python
def get_all_reservations(db) -> dict:
    """Barcha waiting_production band miqdorlari: {(warehouse_id, product_id): qty}.
    Bitta guruhlangan query (per-qator alohida query o'rniga)."""
    rows = (
        db.query(
            func.coalesce(OrderItem.warehouse_id, Order.warehouse_id).label("wh"),
            OrderItem.product_id.label("pid"),
            func.coalesce(func.sum(OrderItem.quantity), 0.0).label("qty"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == "waiting_production", Order.type == "sale")
        .group_by("wh", OrderItem.product_id)
        .all()
    )
    return {(r.wh, r.pid): float(r.qty or 0) for r in rows}
```

### 4.2. Route: `app/routes/reports.py` `report_stock`
- Joriy ko'rinish (report_date yo'q): `reserved_map = get_all_reservations(db)`. Har `stocks` qatoriga:
  `reserved = reserved_map.get((wh_id, pid), 0)`, `free = quantity − reserved`.
  Qator dict'iga `reserved`, `free` qo'shiladi. `show_reserved=True` template'ga.
- Sana-filtri ko'rinishi (report_date bor): band hisoblanmaydi, `show_reserved=False`.
- `_stock_report_filtered` qatorlari hozir `{warehouse, product, quantity}` — bunga `warehouse_id`/`product_id` ham kerak (lookup uchun); qo'shiladi.

### 4.3. Template: `app/templates/reports/stock.html`
- `show_reserved` bo'lsa: jadval sarlavhasiga **BAND** va **ERKIN** ustunlari (QOLDIQ dan keyin).
- Har qator: band (band>0 bo'lsa qizg'ish), erkin.
- `reserved > 0` qatorlar yengil sariq fon.
- Yuqoridagi stat kartalariga: "Band: N pozitsiya" (band>0 qatorlar soni).
- `show_reserved=False` (sana-filtri): ustunlar ko'rsatilmaydi (eski ko'rinish).

## 5. Edge case
- Band yo'q (waiting buyurtma yo'q) → barcha reserved=0, erkin=qoldiq, hech narsa belgilanmaydi (eski ko'rinishga teng).
- Manfiy erkin (band > qoldiq, drift holatida) → ko'rsatiladi (qizil), operatorga signal.
- Sana-filtri → band ustunlari yashirin (hozirgi tushuncha).
- Pozitsiya wh+pid bo'yicha — reserved_map kaliti `(warehouse_id, product_id)`.

## 6. Test strategiyasi
- `get_all_reservations`: waiting buyurtma(lar) bilan to'g'ri dict; bo'sh holatda {}.
- Route-level emas (template), service-level helper + qator boyitish mantig'i unit-test.

## 7. Doiradan tashqari
- Boshqa ekranlar (ombor jurnali, transfer, POS) da band ko'rsatish.
- Excel export'ga band ustuni (kelajak, agar so'ralsa).

## 8. Risk
- **Ma'lumotga ta'sir:** Yo'q (faqat ko'rsatish, read-only).
- **Performance:** 1 ta batch query qo'shiladi (arzon). Deploy: restart kerak (kod+template).
- **Tier:** A/C (faqat ko'rsatish, xulq o'zgarmaydi).
