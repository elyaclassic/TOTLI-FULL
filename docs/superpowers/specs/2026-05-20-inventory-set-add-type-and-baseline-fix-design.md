# Inventarizatsiya: aniq SET/ADD tur + ishonchli baseline (D1+D2 fix)

**Sana:** 2026-05-20
**Branch (taxminiy):** `feat-inventory-type-baseline`
**Tier:** migration A/B (additive), confirm + UI Tier B
**Bog'liq incident:** [[wh2-karobka-reconcile-20260519]] — 4 ta WH2 KAROBKA noto'g'ri/manfiy; data tuzatildi, kod ildizi shu yerda.

## 1. Kontekst va muammo

`/inventory/` moduli `StockAdjustmentDoc` jadvalida ikki xil operatsiya bajaradi:
- **Inventarizatsiya (SET):** jismoniy sanoq → Stock o'sha songa o'rnatiladi.
- **Tovar qoldiqlari (ADD):** kiritilgan son mavjud qoldiq ustiga qo'shiladi.

Ikki defekt birlashganda manfiy/noto'g'ri qoldiq paydo bo'ladi:

**D1 — SET/ADD almashtirgich mo'rt.** `app/routes/warehouse.py` `inventory_confirm` (~1437):
```python
is_stock_entry = bool(doc.number and doc.number.startswith("INV-PENDING"))
```
`inventory_create_draft` har doim `number="INV-PENDING-{id}"` qiladi; confirm uni `INV-YYYYMMDD-NNNN` ga qayta nomlaydi. Re-confirm (revoke→qayta tasdiqlash)da semantika ag'dariladi (INV-PENDING emas → SET). Foydalanuvchi tur tanlay olmaydi; UI `type` ni ko'rsatmaydi.

**D2 — `old_qty` baseline buzuq.** `_apply_inventory_stock_changes` (~1587):
```python
old_qty = float(last_mv.quantity_after or 0)   # last = MAX(id) WHERE created_at<=doc_date
```
`quantity_after` insert vaqtida Stock jadvalining o'sha lahzadagi qiymatidan yoziladi — running balans EMAS. Back-dated sintetik InitialBalance qatorlari (masalan 2026-05-13 `INIT-DRIFT-FIX-W2-*`: `created_at='2026-01-01'` LEKIN eng katta ID, `quantity_after`=xom drift) "oxirgi movement" bo'lib topiladi va `old_qty` ga axlat qaytaradi.

**Birikkan ta'sir (incident 2026-05-19 doc #101):** ADD yo'lida `stock = old_qty + new_qty + after_changes`. P167: −3000 (axlat) + 1800 (jismoniy) + 0 = **−1200**. P185, P166, P108 ham noto'g'ri (4/4 matematik isbot — [[wh2-karobka-reconcile-20260519]]).

**Ishlab chiqarish ta'siri:** P167/P185 KAROBKA manfiy → `strict_negative` orqali shu mahsulotni iste'mol qiladigan ishlab chiqarish bloklandi.

**Kashfiyot:** kodbazada `get_stock_at_date_batch` (`app/utils/stock_at_date.py`) **allaqachon mavjud** va docstring'i muammoni aytadi: *"quantity_after ishonchsiz, chunki insert vaqtida yoziladi"*. U `SUM(quantity_change) WHERE created_at<=cutoff` ishlatadi (back-dated qatorlarni to'g'ri inkor qiladi). `warehouse.py:649` (transfer) da allaqachon ishlatilgan — proven pattern.

## 2. Maqsad va qamrov

**Maqsad:** D1+D2 ni hal qilish; `/inventory/` modulida har confirm Stock va ledger SUM ni jismoniy haqiqatga (yoki ADD'da mavjud+qo'shilgan) mos qiladi, hujjat tur tarixiga qaramay.

**Qamrov ichida:**
1. `stock_adjustment_docs.type` ustuni (`'inventory'` | `'stock_entry'`), additive migratsiya + ORM model
2. `app/routes/warehouse.py`: `inventory_create_draft`, `inventory_confirm`, `_apply_inventory_stock_changes`
3. `app/templates/inventory/new.html`, `inventory/edit.html`, `inventory/list.html`, `inventory/view.html`
4. Backfill skript: mavjud ~100 hujjat (harakat note'idan haqiqiy semantika)
5. Regressiya testi (back-dated sintetik qator stsenariysi)

**Qamrovdan tashqari:**
- `/qoldiqlar/tovar/hujjat` moduli (alohida confirm, QLD prefiks): tegilmaydi; faqat `type` backfill oladi (hisobot moslik uchun)
- WH2'da qolgan ~60 stacked-INIT data drift: [[etiketka-drift-strategy]] bo'yicha qoladi; kod fix kelajakni himoya qiladi, o'tmish ledger drift'i SET'da o'z-o'zini tuzatadi (Bo'lim 5 ga qarang)
- Ikki modul birlashtirish (C yondashuvi): alohida brainstorm/spec keyinga

## 3. Yondashuv

**A — `type` ustuni + `get_stock_at_date_batch` baseline (TANLANGAN).** Ikkala defektni mavjud helper bilan hal qiladi, qamrov tor, migratsiya additive, jonli prodga past xavf.

**B — `type` ustuni + `quantity_after` ga guard.** D2 ni `get_stock_at_date` ga o'tmasdan, sintetik InitialBalance ni aniqlash guard'i bilan tuzatadi. Mavjud helper mantiqini qisman qayta ixtiro qiladi. Rad.

**C — `/inventory/` va `/qoldiqlar/` birlashtirish.** Uzoq muddatli takror muammosini hal qiladi, lekin Tier C, katta qamrov, bugfix doirasidan tashqari. Keyinga qoldirilgan.

## 4. Ma'lumotlar modeli + migratsiya

**Schema o'zgarishi (additive):**
```sql
ALTER TABLE stock_adjustment_docs
  ADD COLUMN type VARCHAR(20) DEFAULT 'inventory';
```
- Nullable; runtime default `'inventory'`
- Indekslanmaydi (kardinalligi 2, foyda yo'q)
- Alembic migratsiya + downgrade skripti (`ALTER TABLE ... DROP COLUMN type`)
- SQLAlchemy modelга `type = Column(String(20), default="inventory")` qo'shiladi ([[feedback_orm_db_schema_drift]] — ORM va DB birga)
- Bootstrap'da `ensure_*_column(...)` chaqirig'i, pending tranzaksiya tashqarisida ([[feedback_schema_migration_pattern]])

**Backfill (harakat note'idan, prefiksdan emas):**
```python
# Har doc uchun unga tegishli movement note'lari:
#   stock_movements WHERE document_type='StockAdjustmentDoc' AND document_id=doc.id
for doc in stock_adjustment_docs:
    notes = [m.note for m in movements_for(doc)]
    if any(n and n.startswith(("Tovar qoldiqlari", "Qoldiq kiritish")) for n in notes):
        doc.type = "stock_entry"
    elif any(n and n.startswith("Inventarizatsiya") for n in notes):
        doc.type = "inventory"
    elif (doc.number or "").startswith("QLD"):
        doc.type = "stock_entry"        # QLD = qo'shish, harakatsiz draft uchun
    else:
        doc.type = "inventory"          # draft/qolgan default
```
Dry-run majburiy; tasdiq oldidan jami soni va namuna 10 qator chiqariladi.

## 5. Confirm logikasi tuzatish (yadro — D2)

**`inventory_confirm` (~1437):**
```python
# eski:
is_stock_entry = bool(doc.number and doc.number.startswith("INV-PENDING"))
# yangi:
is_stock_entry = (doc.type == "stock_entry")
```
Hujjat raqamlash mantiq'i o'zgarmaydi — `INV-PENDING` faqat raqam placeholder, semantika `type` da.

**Confirm POST tur qayta tasdig'i:**
```python
posted_type = form.get("type")
if posted_type and posted_type != doc.type:
    return redirect(f"/inventory/{doc_id}/edit?message=Tur mos kelmadi")
```

**`_apply_inventory_stock_changes` — baseline almashtirish:**
- `last_mv_by_pair` va `stock_sum_fallback` qurilishi olib tashlanadi
- O'rniga: warehouse bo'yicha guruhlab `get_stock_at_date_batch(db, wh_id, pids, cutoff=doc_date)` chaqirig'i — `old_qty_by_pair` dict
- `after_changes_by_pair` (mavjud, `operation_type != 'adjustment' AND created_at > doc_date`) o'zgarmaydi
- Loop ichida:
  - `old_qty = old_qty_by_pair[(wh,pid)]` (default 0.0)
  - `quantity_change = new_qty if is_stock_entry else (new_qty - old_qty)`
  - `create_stock_movement(quantity_change, created_at=doc.date)` o'zgarmaydi
  - `stock_row.quantity = (old_qty + new_qty + after_changes) if is_stock_entry else (new_qty + after_changes)` o'zgarmaydi

**Matematik invariant (tuzatishdan keyin):** ledger SUM == yakuniy Stock ikkala rejimda ham.
- SET: ledger = `old + (new−old) + after = new + after` = Stock ✓
- ADD: ledger = `old + new + after` = Stock ✓

**O'z-o'zini tuzatish xususiyati:** SET rejimida ledger drift'i (stacked-INIT) avtomatik yopiladi (`new−old` reconcile mv). Kelajak inventarizatsiyalar drift'ni assimilatsiya qiladi — keyingi avtomatik tozalanish davri.

## 6. UI oqimi

**`/inventory/new` (yaratish):**
- Ombor tanlashdan keyin 2 ta radio:
  - ◉ **Inventarizatsiya** — *mavjud qoldiqni jismoniy songa o'rnatadi* (default)
  - ○ **Tovar qoldiqlari** — *kiritilgan sonni mavjud qoldiqqa qo'shadi*
- `inventory_create_draft` `type` ni `Form(...)` dan oladi, `StockAdjustmentDoc(type=...)`

**`/inventory/{id}/edit`:**
- Sahifa tepasida tur badge: "**Inventarizatsiya** — qoldiq jismoniy songa o'rnatiladi" (yoki ADD matni)
- Tasdiqlash blokida yashirin `<input name="type" value="{{ doc.type }}">` + tugma matni turga moslashadi: "Inventarizatsiya sifatida tasdiqlash" / "Tovar qoldiqlari sifatida tasdiqlash"
- Tur o'zgartirish kerak bo'lsa: hujjatni o'chirib qayta yaratiladi (tahrirlash juda kam — semantika xavfi)

**`/inventory` (ro'yxat) va `/inventory/{id}` (ko'rish):** har qatorda/sahifada tur badge.

## 7. Xatolar va chekka holatlar

| Holat | Xatti-harakat |
|---|---|
| `doc.type` NULL (eski draft) | `type or 'inventory'` — xavfsiz default SET |
| Confirm POST `type` ≠ `doc.type` | 303 redirect xabar bilan; yozuv yo'q |
| Multi-warehouse doc | `get_stock_at_date_batch` har warehouse uchun alohida chaqiriladi |
| Re-confirm (revoke→qayta) | `type` saqlanadi → semantika ag'darilmaydi (eski bug yo'q) |
| `get_stock_at_date_batch` 0 qaytarsa | `old_qty=0` — to'g'ri (yangi mahsulot) |
| Atomiklik | Mavjud `try/_merge_duplicate_stock_rows/_apply.../commit` bitta tranzaksiya — o'zgarmaydi |
| Avval `inventory_revoke` ishlatishi | `type` ustuni rivertda o'zgarmaydi |

## 8. Test rejasi

**Asosiy regressiya (TDD — avval failing):**
1. **Back-dated sintetik baseline tuzog'i (D2):** test fixturasi — bitta mahsulot uchun:
   - `created_at='2026-01-01'`, eng katta ID, `quantity_after=−3000`, `quantity_change=−3000` movement
   - Boshqa real movementlar (chronologik balans ≠ −3000)
   - Confirm `type='inventory'`, jismoniy=1800
   - **Kutilgan:** Stock=1800, ledger SUM=1800
   - **Eski kod:** Stock=−1200 (test yiqiladi, bagni ushlaydi)

2. **`type='stock_entry'` ADD semantika:** old=100, new=50 → Stock=150, ledger=150. **Eski kod:** INV-PENDING prefiksi bo'lmasa SET'ga tushadi (bug). **Yangi:** to'g'ri ADD.

3. **`type` ag'darilishi (re-confirm):** confirm → revoke → qayta confirm. Semantika o'zgarmasligi.

4. **Multi-warehouse doc:** ikki ombor itemli doc → ikki `get_stock_at_date_batch` chaqirig'i, har biri to'g'ri baseline.

5. **`type` POST mos kelmasligi:** redirect, hech narsa yozilmaydi.

**Backfill testi:** sun'iy doc + movement note → kutilgan `type` mapping.

**Smoke:** `/inventory/new` (har 2 tur), draft yaratish, tahrir, confirm, ro'yxat, view — barchasi 200 va ko'rinish to'g'ri.

**Regressiya bo'lmasligi:** `tests/test_refactor_modules.py` o'tadi.

## 9. Tier va deploy strategiyasi

- **Migratsiya (column add + ORM model + backfill):** Tier A/B (additive nullable+default). Tungi oyna kerak emas (xavfsiz), lekin barcha tungi oynaga birga olib boriladi.
- **Confirm logikasi + UI:** Tier B. Tungi oyna 00:00–04:00, backup oldin, smoke keyin.
- **Feature flag SHART EMAS:** eski data backfill bilan saqlanadi (semantika tiklanadi), yangi hujjatlar aniq `type` oladi. Eski xulq ehtiyot uchun saqlanmaydi (chunki u BUG edi).

**Deploy buyrug'i ketma-ketligi:**
1. `git checkout -b feat-inventory-type-baseline`
2. Migration commit (column + ORM + ensure helper)
3. Confirm logikasi + UI commitlar
4. Testlar yashil
5. Tungi oyna: `git stash` (agar ish bor) → DB backup → restart → migration auto-apply → backfill skript dry-run → tasdiq → `--apply` → smoke (har 2 tur uchun)

## 10. Rollback

- **Kod:** `git revert` 1 commit (yoki bir nechta — kichik atomik commitlar bilan)
- **Schema:** column qoladi (nullable, default) — eski kod `type` ni o'qimaydi, ta'sir yo'q. Down migration faqat butun feature qaytarishda.
- **Backfill data:** harakat note'lariga teginadi emas, faqat `type` ustun. Rollback uchun `UPDATE stock_adjustment_docs SET type=NULL` (yoki backup'dan tiklash).
- **DB backup:** tungi oyna boshida standart `.bak`

## 11. Bog'liq

- [[wh2-karobka-reconcile-20260519]] — incident, data fix
- [[wh2-inventory-is-stock-entry-bug]] — kod ildiz tahlili (shu spec yopadi)
- [[project_stock_at_date_pattern]] — `get_stock_at_date` proven pattern
- [[stock-drift-reconciliation-20260513]] — back-dated sintetik qatorlar manbai
- [[etiketka-drift-strategy]] — qolgan stacked-INIT data strategiyasi
- [[feedback_orm_db_schema_drift]] — ORM va DB schema birga yangilash
- [[feedback_schema_migration_pattern]] — `ensure_*_column` pending tranzaksiya tashqarisida
- [[feedback_safe_deployment]] — Tier A/B/C qoidalari
