# purchase_price korruption fix — dizayn spec

**Sana:** 2026-05-16
**Branch:** `safe-fix-purchase-price` ← `feat-bulk-dispatch` (prod liniyasi)
**Tier:** C (issiq yozuv yo'li o'zgaradi + ommaviy ma'lumot mutatsiyasi)
**Aloqador:** [[project_purchase_price_corruption]], sales-metrics deploy darslari ([[project_sales_metrics_refactor_20260516]])

## 1. Muammo

Ishlab chiqariladigan mahsulotning `Product.purchase_price` qiymati `production.py:_update_output_cost_and_price` (249-270) da har `completed` ishlab chiqarishda qo'riqsiz qayta yoziladi.

**Ildiz — feedback rekursiyasi:** `purchase_price = f(eski purchase_price, cost_per_unit)` (weighted-avg) yoki `stock<=0` da to'g'ridan-to'g'ri `= cost_per_unit` (flat, sanity yo'q). O'z chiqishini qayta kiritadi → langarsiz, cheksiz suriladi. Tarixga (`product_price_history`) yozilmaydi → ko'rinmaydi.

**Ko'lam:** 166 aktiv retseptli mahsulotdan **136 tasi (82%)** narx-tarixi 2026-05-01'dan eski/yo'q. Misol: KITOB 1 (1kg) pp 05-15 da 463,965 → hozir 66,997 (beqaror sakraydi); MAYDA PISTA 1kg pp 66,684 (kutilgan ~39,768), sotuv 64,462 → soxta −3.4% zarar. Sotilgan mahsulotlar hisobotida soxta zararlar.

**Sales-metrics refactoridan ALOHIDA** (u faqat read; bu COGS manbai, spec §7'da qamrov tashqarisi edi).

## 2. Qaror qilingan ta'riflar

- **Forward-fix arxitekturasi:** `purchase_price` = production allaqachon hisoblagan **dona boshiga** `cost_per_unit` (flat tayinlash, weighted-avg/flat-feedback YO'Q) + har o'zgarishni `product_price_history`ga yozish + sanity-log. Sabab: self-feedback rekursiyani uzadi (`pp` o'zining eski qiymatiga bog'liq emas, langar = batch material narxi). `cost_per_unit` hujjatdagi tannarx bilan bir xil manba, birlik to'g'ri.
- **Reconcile:** barcha aktiv retseptli mahsulot (136 amalda o'zgaradi) — jonli batch yo'q, shuning uchun statik retsept-narx `_calculate_recipe_cost_per_kg(recipe) × recipe_kg_per_unit(recipe)` (kg-narx × kg/dona = **dona boshiga**) + tarixga yoziladi.
- **Rollout:** birlashgan — bitta tungi oyna: kod fix + backfill + verifikatsiya.
- **Yondashuv:** A1 — in-place. Jonli yo'l mavjud `cost_per_unit`ni qayta ishlatadi (yangi tannarx-mantiq YO'Q). Backfill mavjud `_calculate_recipe_cost_per_kg` + `recipe_kg_per_unit`ni ishlatadi. Yangi servis moduli EMAS (YAGNI).

> **KORREKTLIK TUZATISHI 2026-05-16:** dastlabki spec jonli yo'lda `_calculate_recipe_cost_per_kg` (kg-narx) ni to'g'ridan-to'g'ri pp ga yozardi — bu sub-kg SKU'larni (400gr → 2.5×) qayta shishirardi. Jonli yo'l endi dona-to'g'ri `cost_per_unit`ni ishlatadi; faqat backfill (batch konteksti yo'q) statik `recipe_cost_per_kg × kg_per_unit` ishlatadi.

## 3. Forward-fix (`app/routes/production.py`)

`_update_output_cost_and_price` signaturasi: `output_units` (endi kerak emas) olib tashlanadi, `production` qo'shiladi → `_update_output_cost_and_price(db, out_wh_id, recipe, cost_per_unit, production)`. Yagona chaqiruvchi `production.py:319` mos yangilanadi (`cost_per_unit` allaqachon shu yerda, `production` ham scope'da). Ichidagi weighted-avg/flat blok (256-270) almashtiriladi:

```python
cost = cost_per_unit  # production allaqachon hisoblagan dona-narx (hujjat tannarxi bilan bir manba)
if cost and cost > 0:
    old = output_product.purchase_price or 0
    output_product.purchase_price = cost
    if product_stock is not None and hasattr(Stock, "cost_price"):
        product_stock.cost_price = cost
    _log_price_history(db, output_product, old, cost, production.number)
    if output_product.sale_price and cost > output_product.sale_price:
        logger.warning("PRICE ANOMALY %s: tannarx %.0f > sotuv %.0f",
                        output_product.name, cost, output_product.sale_price)
# cost <= 0 -> o'zgartirilmaydi (eski qiymat saqlanadi, nolga tushirilmaydi)
```

`product_stock` lookup (251-254) saqlanadi (cost_price izchilligi uchun). `_calculate_recipe_cost_per_kg` jonli yo'lda CHAQIRILMAYDI.

Yangi helper:

```python
def _log_price_history(db, product, old_pp, new_pp, doc_number):
    if abs((old_pp or 0) - (new_pp or 0)) < 1e-6:
        return
    db.add(ProductPriceHistory(
        doc_number=doc_number, product_id=product.id, price_type_id=None,
        old_purchase_price=float(old_pp or 0), new_purchase_price=float(new_pp or 0),
        old_sale_price=float(product.sale_price or 0),
        new_sale_price=float(product.sale_price or 0),
        changed_by_id=None,
    ))
```

**Tamoyillar:**
- `cost <= 0` → pp tegilmaydi (CLAUDE.md: nol/manfiy clamp ma'lumot yo'qotadi).
- Anomaliya bloklamaydi — faqat `logger.warning` (zavod to'xtamasin).
- `changed_by_id=None` = tizim o'zgarishi (qo'lda emas).
- Signatura: `_update_output_cost_and_price(db, out_wh_id, recipe, cost_per_unit, production)` — `output_units` olib tashlandi, `production` qo'shildi (doc_number uchun). Chaqiruvchi production.py:319 mos yangilanadi.

## 4. Backfill skript (`scripts/backfill_produced_purchase_price.py`)

```
python scripts/backfill_produced_purchase_price.py [db_path] [--apply]
```

- Default = DRY-RUN (faqat hisobot, yozish yo'q). `--apply` = yozadi.
- Aktiv retseptli mahsulotlar: `SELECT DISTINCT product_id FROM recipes WHERE is_active=1`.
- Har biri: `new = _calculate_recipe_cost_per_kg(db, recipe.id) * recipe_kg_per_unit(recipe)` — **dona boshiga** (kg-narx × kg/dona; faqat per-kg ishlatish 400gr SKU'larni qayta shishirardi). Topologik tartib SHART EMAS (helper o'zi rekursiv daraxtni hisoblaydi — yarim-tayyorni o'z retseptidan, saqlangan buzuq pp'dan emas). Bir mahsulotda bir nechta aktiv retsept bo'lsa: birinchisi (`recipes.id` bo'yicha) olinadi.
- Barcha aktiv retseptli mahsulot ko'riladi (166); `new > 0` VA `|old-new| >= 1e-6` bo'lsa → `Product.purchase_price`, har ombordagi `Stock.cost_price`, + `ProductPriceHistory` (`doc_number="BACKFILL-YYYYMMDD"`). Allaqachon to'g'ri (o'zgarmas) mahsulotlar tegilmaydi/tarixga yozilmaydi (§1'dagi 136 buzuq — amalda shu o'zgaradi).
- `new <= 0` → o'tkazib yuboriladi, hisobotda "retsept bo'sh" deb belgilanadi.
- **Chekka holat:** retseptsiz yarim-tayyor komponent `_calculate_recipe_cost_per_kg`da saqlangan pp'ga tushadi (89-93 qator) — agar uning pp'si buzuq bo'lsa tarqaydi. Bu 166 to'plamga kirmaydi (retsepti yo'q). DRY-RUN `new>sale_price` anomaliyasi gross holatlarni belgilaydi; chuqurroq raw/semi audit §7.
- Hisobot: `old → new`, farq %, `new > sale_price` bo'lganlar ✱ (buzuq xom ashyo/semi belgisi).
- Bitta tranzaksiya (oxirida `commit`, xato → `rollback`). Idempotent (deterministik, qayta yuritish xavfsiz).

## 5. Test (`tests/test_production_cost.py`, conftest `db`)

1. `_calculate_recipe_cost_per_kg × recipe_kg_per_unit`: oddiy 2-ingredient retsept, 400gr SKU → dona-narx (kg-narx EMAS; 2.5× shishish yo'qligini pin qiladi).
2. Yarim-tayyor rekursiv: semi retsepti orqali (saqlangan buzuq pp'ga emas).
3. `_update_output_cost_and_price`: pp == uzatilgan `cost_per_unit` (weighted-avg yo'q); old_pp ataylab buzuq qiymatga qo'yilib chaqirilsa ham natija `cost_per_unit`ga teng + **2-marta chaqir → o'zgarmaydi** (idempotent = feedback-rekursiya o'lgani isboti, eski bug regressiya guard).
4. `cost <= 0` → pp o'zgarmaydi.
5. Har chaqiruv `ProductPriceHistory` qatori yozadi; o'zgarmasa yozmaydi.
6. `cost > sale_price` → warning log, production bloklanmaydi (normal qaytadi).
7. Backfill: dry-run hech narsa yozmaydi; apply idempotent (2-marta = bir xil natija).

## 6. Deploy (birlashgan, tungi oyna)

| Qadam | Tafsilot |
|---|---|
| Branch | `safe-fix-purchase-price` ← `feat-bulk-dispatch` |
| Backup | git tag `pre-purchase-price-YYYYMMDD` + DB dump (mutatsiya — majburiy) |
| Pre | server2220'da DRY-RUN → 166 `old→new` + `>sale_price` anomaliyalar ko'rib chiqiladi. Anomaliya ko'p → TO'XTA, avval xom ashyo narxi tuzatiladi (A ning yagona qoldiq xavfi; DRY-RUN ushlaydi) |
| Deploy | merge → **server2220 konsolida** (ELYOR'dan emas) `cd /d D:\TOTLI BI` → taskkill → start.bat |
| Backfill | server2220'da `--apply` (bitta tranzaksiya) |
| Post | sold-products: produced mahsulot soxta zarari yo'qoldi; MAYDA PISTA 1kg/KITOB 1 musbat marja; 3-4 spot-check; `10.243.165.156:8080` (127.0.0.1 emas) |
| Rollback | Kod: `git revert`. Ma'lumot: `BACKFILL-` tarix qatorlaridan `old_purchase_price` tiklash skripti yoki DB dump restore. Idempotent → qayta yuritish xavfsiz |

## 7. Scope tashqarisi (ataylab)

- Xom ashyo (raw) `purchase_price` audit — Purchase hujjatlaridan keladi, ishonchli; DRY-RUN anomaliyasi belgilasa alohida ko'riladi. Bu spec'da to'liq audit qilinmaydi.
- `document_service.py` / `info.py` / `qoldiqlar.py` / `warehouse.py` dagi boshqa `purchase_price=` yo'llari — production rollup bug'i emas, tegilmaydi.
- sales-metrics worktree tozalash — alohida.
