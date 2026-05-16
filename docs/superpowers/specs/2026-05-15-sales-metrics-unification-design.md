# Sales-metrics yagona helper — dizayn spec

**Sana:** 2026-05-15
**Branch:** `safe-fix-sales-metrics` (main'dan)
**Tier:** B'ga yaqin (faqat read yo'llari, schema/migratsiya/mutatsiya YO'Q)

## 1. Muammo

Sotuv summasi tizimda 4 ta endpoint'da 4 xil ta'rifda hisoblanadi — bironta ham mos kelmaydi:

| Endpoint | Holat qamrovi | Sana maydoni | Summa asosi |
|---|---|---|---|
| `/sales` (Sotuvlar) | `completed+delivered+confirmed` | `Order.date` | `Order.total` |
| `/reports/sales` (Savdo) | HAMMASI (cancelled ham) | `Order.date` | `Order.total` |
| `/reports/profit` (Foyda) | `status != cancelled` | `Order.date` | `Order.total` |
| `/reports/sold-products` | `completed+delivered` | `Order.created_at` | `Σ OrderItem×chegirma` |

Namuna (01.05–15.05): Savdo 608,847,869 / Foyda 603,532,869 / Sotilgan 596,093,869.
Farq ildizi: "qaysi buyurtma sanaladi" ta'rifi 4 joyda mustaqil takrorlangan → drift.

## 2. Qaror qilingan ta'riflar

- **Realized (haqiqiy) sotuv** = status `delivered` + `completed` + `confirmed` + `out_for_delivery` — `out_for_delivery`'da stock allaqachon ombordan ketgan, shuning uchun qat'iy sotuv (bugun 0 qator, raqam o'zgarmaydi, ammo latent revenue-undercount bug oldini oladi).
- **Sana maydoni** = `Order.date` (biznes sanasi), doimo
- **Yondashuv** = query-builder + scope konstantalar (C-darajadagi to'liq agregatsiya servisi EMAS — YAGNI)
- **Cancelled** `/reports/sales` ro'yxatida qoladi (kulrang, audit uchun), lekin summadan chiqadi

## 3. Modul: `app/services/sales_metrics.py`

`finance_service.cash_balance_formula()` etalon uslubida — yagona haqiqat manbai.

```python
SALE_REALIZED = ("delivered", "completed", "confirmed", "out_for_delivery")  # daromad/foyda

def sale_orders_query(db, *, scope="realized", dt_from=None, dt_to=None,
                      warehouse_id=None, partner_id=None) -> Query:
    """type=='sale' Order query'si. Sana doimo Order.date.
    scope='realized' → status IN SALE_REALIZED
    scope='all'      → status filtri yo'q (cancelled ham — ro'yxat uchun)
    Endpoint query'ni o'zi kengaytiradi (paginatsiya, JOIN, agregatsiya)."""

def sale_revenue(db, *, dt_from, dt_to, warehouse_id=None, partner_id=None) -> float:
    """realized bo'yicha Σ Order.total — bitta skalyar."""
```

**Tamoyillar:**
- Faqat 2 scope: `realized`, `all`. `confirmed` realized ichida, alohida "pipeline" scope kerak emas.
- Helper **Query** qaytaradi (skalyar emas) → har endpoint o'z shaklini saqlaydi.
- Sana parsing kiritilmaydi (alohida kichik muammo, scope tashqarisi).
- Modul tashqarisida `Order.status.in_(...)` yozilmaydi — ta'rif faqat shu yerda.

## 4. Endpoint integratsiyasi va kutilgan raqam ta'siri

| Endpoint | O'zgarish | Ko'rinadigan ta'sir |
|---|---|---|
| `/sales` | stats/pay/chegirma/tannarx → helper konstantasi. Ro'yxat query'si `scope="all"` (jadval barcha hujjat — operatsion). "Qoralama" yorlig'i → haqiqiy `status="draft"` soni, qolgani "Boshqa holat" | **O'zgarmaydi** (faqat dedup) |
| `/reports/sales` | Ro'yxat: `sale_orders_query(scope="all")`. Total: `sale_revenue()`. Template: cancelled qator kulrang | **Total ↓** ≈ cancelled summasi (namunada −5,315,000) |
| `/reports/profit` | `_compute_sales_and_cogs` → `sale_orders_query(scope="realized")`. Qaytarish mantiqi o'zgarmaydi | **Revenue ↓** = (draft+waiting_production+out_for_delivery+pending) summasi |
| `/reports/sold-products` | order-id to'plami → `sale_orders_query(scope="realized")`; `created_at`→`Order.date`. Per-product item-level sum saqlanadi | **↕** confirmed qo'shiladi (↑), created_at→date siljish |

**Ma'lum, qabul qilingan farq:** sold-products per-product chegirma proporsional sum baribir `Σ Order.total`dan biroz farq qiladi (yaxlitlash, `product_id` NULL qatorlar). Bu maqsadli — sold-products mahsulot tahlili, scope kengaytirilmaydi.

## 5. Test strategiyasi

1. **Unit** (`tests/test_sales_metrics.py`): realized faqat 3 status; all cancelled'ni oladi; sana chegarasi inklюзив; warehouse/partner filtri; bo'sh davr → 0.
2. **Reconciliation invariant:** bir davr/filtr uchun `/sales` jami == `sale_revenue()` == `Σ realized Order.total` — uchchalasi teng. (Hozir buzilgan; o'tsa bug yo'q.)
3. **Before/after snapshot** (`scripts/sales_metrics_snapshot.py`): deploy oldidan/keyin 4 sahifa raqamini bir nechta davr uchun yozadi, deltani izohlaydi. Tushuntirib bo'lmaydigan delta → rollback.

## 6. Xavfsiz deploy

> **TUZATISH 2026-05-16:** Asl spec "`main`'dan branch" degandi — bu **xato**. Aniqlandi: `main` (origin/main) prod liniyasidan **50+ commit eskirgan**; prod aslida `feat-bulk-dispatch`'da ishlaydi (Sotilgan mahsulotlar discount/profit ustunlari faqat shu yerda). Shu sabab feature `feat-bulk-dispatch` bazasida qurildi (branch `sales-metrics-feat`). `main`'ga rebase qilish — biz tuzatgan baza-nomuvofiqlik bug'ini qaytaradi, shuning uchun QILINMAYDI.

- **Branch:** `sales-metrics-feat` ← `feat-bulk-dispatch` (prod liniyasi). Faqat shu feature'ga tegishli 8 fayl, 14 commit — aloqasiz WIP "tortilmaydi" chunki u allaqachon `feat-bulk-dispatch`'da
- **Merge target:** `feat-bulk-dispatch` (prod liniyasi) — `main` EMAS. (Loyiha git-gigienasi alohida masala: `main` qachondir `feat-bulk-dispatch`'ga yetkazilishi kerak — bu refactordan tashqari.)
- **Backup:** git tag + DB dump
- **Feature flag:** YO'Q — read-only, `git revert` bir zumda qaytaradi (flag = keraksiz murakkablik)
- **Oyna:** tungi 00:00–04:00 (23:00 backup tugagach)
- **Pre-deploy:** snapshot skript (eski raqamlar) — kutilgan delta: savdo total −cancelled (~−9.0M joriy oy), profit revenue −(draft+waiting+pending) (~−3.7M), out_for_delivery=0
- **Deploy:** `feat-bulk-dispatch`'ga merge → `taskkill python.exe` → `start.bat`
- **Post-smoke:** 4 sahifa + export ochiladi (xato yo'q) + snapshot qayta → delta izohlanadi
- **Rollback:** 14 feature commit izolyatsiyalangan (8 fayl) → `git revert <merge>` + restart (~1 daq, ma'lumot xavfi 0)

## 7. Scope tashqarisi (ataylab)

- `Product.purchase_price` production rollup'da buzilishi — ALOHIDA masala, [[project_purchase_price_corruption]] memory'da. Bu spec'da TUZATILMAYDI (boshqa ildiz-sabab, retsept/komponent audit kerak).
- Sana formatlari parsing farqi (`T` vs `date`) — alohida kichik muammo.
- Sotilgan mahsulotlar per-product sum metodi — o'zgarmaydi.
