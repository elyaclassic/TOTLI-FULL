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

> **KRITIK TUZATISH 2026-05-16 (code-review):** `ProductPriceHistory.doc_number` **UNIQUE** (database.py:321). Dastlabki spec `doc_number=production.number` yozardi → bekor-qilib-qayta-tasdiqlash (o'zgargan tannarx bilan) oqimida ikkinchi INSERT IntegrityError → **butun production confirm rollback** (reproduce qilindi). Tuzatish: `_log_price_history` o'zi **unique** `PRC-YYYYMMDD-NNN` raqam generatsiya qiladi (info.py'dagi PN- patterni, lekin issiq yo'lni info route'iga bog'lamaslik uchun mahalliy, distinct prefix). `production` endi kerak emas → signaturadan olib tashlanadi.

`_update_output_cost_and_price` signaturasi: `output_units` VA `production` olib tashlanadi → `_update_output_cost_and_price(db, out_wh_id, recipe, cost_per_unit)`. Yagona chaqiruvchi `production.py:~319` mos yangilanadi (`cost_per_unit` allaqachon shu yerda). Ichidagi weighted-avg/flat blok almashtiriladi:

```python
cost = cost_per_unit  # production allaqachon hisoblagan dona-narx (hujjat tannarxi bilan bir manba)
if cost and cost > 0:
    old = output_product.purchase_price or 0
    output_product.purchase_price = cost
    if product_stock is not None and hasattr(Stock, "cost_price"):
        product_stock.cost_price = cost
    _log_price_history(db, output_product, old, cost)
    db.flush()
    if output_product.sale_price and cost > output_product.sale_price:
        logger.warning("PRICE ANOMALY %s: tannarx %.0f > sotuv %.0f",
                        output_product.name, cost, output_product.sale_price)
# cost <= 0 -> o'zgartirilmaydi (eski qiymat saqlanadi, nolga tushirilmaydi)
```

`product_stock` lookup saqlanadi (cost_price izchilligi uchun). `_calculate_recipe_cost_per_kg` jonli yo'lda CHAQIRILMAYDI.

Yangi helper (o'zi unique doc_number generatsiya qiladi):

```python
def _log_price_history(db, product, old_pp, new_pp):
    if abs((old_pp or 0) - (new_pp or 0)) < 1e-6:
        return
    from app.models.database import ProductPriceHistory
    prefix = f"PRC-{datetime.now().strftime('%Y%m%d')}-"
    last = (db.query(ProductPriceHistory)
              .filter(ProductPriceHistory.doc_number.like(f"{prefix}%"))
              .order_by(ProductPriceHistory.id.desc()).first())
    try:
        num = (int(last.doc_number.rsplit("-", 1)[-1]) + 1) if last and last.doc_number else 1
    except (ValueError, IndexError):
        num = 1
    db.add(ProductPriceHistory(
        doc_number=f"{prefix}{num:03d}", product_id=product.id, price_type_id=None,
        old_purchase_price=float(old_pp or 0), new_purchase_price=float(new_pp or 0),
        old_sale_price=float(product.sale_price or 0),
        new_sale_price=float(product.sale_price or 0),
        changed_by_id=None,
    ))
```

`PRC-` prefiks production-driven o'zgarishlarni qo'lda `PN-` tahrirdan ajratadi (audit). `datetime` production.py'da allaqachon import qilingan.

**Tamoyillar:**
- `cost <= 0` → pp tegilmaydi (CLAUDE.md: nol/manfiy clamp ma'lumot yo'qotadi).
- Anomaliya bloklamaydi — faqat `logger.warning` (zavod to'xtamasin).
- `changed_by_id=None` = tizim o'zgarishi (qo'lda emas).
- pp/cost_price/history yozilgach `db.flush()` (sessiya `autoflush=False`; chaqiruvchi `_do_complete_production_stock` ham flush qiladi, tashqi request commit qiladi — semantik o'zgarmaydi, faqat pending yozuvlar sinxronlanadi). Anomaliya tekshiruvidan oldin.
- Signatura: `_update_output_cost_and_price(db, out_wh_id, recipe, cost_per_unit, production)` — `output_units` olib tashlandi, `production` qo'shildi (doc_number uchun). Chaqiruvchi production.py:319 mos yangilanadi.

## 4. Backfill skript (`scripts/backfill_produced_purchase_price.py`)

```
python scripts/backfill_produced_purchase_price.py [db_path] [--apply]
```

- Default = DRY-RUN (faqat hisobot, yozish yo'q). `--apply` = yozadi.
- Aktiv retseptli mahsulotlar: `SELECT DISTINCT product_id FROM recipes WHERE is_active=1`.
- **OWN FIXED-POINT COST (KRITIK — C1 v2 code-review):** backfill `_calculate_recipe_cost_per_kg`'ga TAYANMAYDI — u faqat `yarim_tayyor`+sub-recipe uchun rekursiya qiladi; o'z aktiv-retseptli `tayyor` oraliq mahsulot uchun saqlangan (buzuq) pp'ni o'qiydi (production.py:94-99). Jonli bazada 24 ta shunday ko'p-bosqichli zanjir → har qanday bir-o'tishli backfill noto'g'ri. Backfill o'z funksiyasini ishlatadi: **`_calculate_recipe_cost_per_kg`'ning aniq strukturaviy nusxasi, BITTA o'zgarish bilan** — rekursiya sharti `input.type=='yarim_tayyor' va sub-recipe bor` emas, **`input'da aktiv retsept bor (har qanday tur)`**. Rekursiyalanadigan input: `item.quantity * own_cost_per_kg(input_recipe)` (asl semi-with-recipe bilan AYNAN bir xil birlik mantiq). Aktiv retseptsiz input (haqiqiy xom ashyo / retseptsiz semi) → saqlangan `purchase_price`/`Stock.cost_price` (asl `else` shoxidek). Memoizatsiya `recipe_id→cost_per_kg`, cycle-guard (asl 58-qatordek). Bu — qurilishi bo'yicha **fixed-point**: order-independent, idempotent, ko'p-bosqichli zanjirni BIR o'tishda to'g'rilaydi. Faqat haqiqiy xom ashyoda (real Purchase narxi) to'xtaydi.
- `new = own_cost_per_kg(recipe) * recipe_kg_per_unit(recipe)` — **dona boshiga** (faqat per-kg 400gr'ni shishirardi). Bir mahsulotda bir nechta aktiv retsept: birinchisi (`recipes.id` bo'yicha).
- **TWO-PHASE:** Phase 1 — barcha `new` HECH NARSA YOZMASDAN hisoblanadi (own-cost o'zi to'liq rekursiv fixed-point, DB holatiga emas hisobga tayanadi → baribir order-independent; two-phase qo'shimcha himoya: Phase 1'da yozuv yo'q). Phase 2 — `apply` bo'lsa Phase 1 natijalaridan yoziladi.
- `new > 0` VA `|old-new| >= 1e-6` bo'lsa → `Product.purchase_price`, har ombordagi `Stock.cost_price`, + `ProductPriceHistory` (unique `BACKFILL-YYYYMMDD-NNN`). Allaqachon to'g'rilar tegilmaydi.
- `new <= 0` → `SKIP(retsept bo'sh)`.
- **Chekka holat:** retseptsiz semi/raw saqlangan pp'ga tushadi — agar uning pp'si buzuq bo'lsa tarqaladi. Lekin bunday input 166 to'plamga kirmaydi (retsepti yo'q); `SUSPECT`/`ANOMALY` DRY-RUN'da belgilaydi; chuqurroq raw audit §7.
- Hisobot: `old → new`, farq %, `new > sale_price` → `ANOMALY` ✱; **`|farq| > 70%` → `SUSPECT`** (to'liqsiz retsept ehtimoli, masalan Rulet mevali 1.5kg 72k→3k; operator DRY-RUN'da vetting qiladi).
- Bitta tranzaksiya (Phase 2 oxirida `commit`, xato → `rollback`). Idempotent (two-phase + deterministik, qayta yuritish true no-op).

## 5. Test (`tests/test_production_cost.py`, conftest `db`)

1. `_calculate_recipe_cost_per_kg × recipe_kg_per_unit`: oddiy 2-ingredient retsept, 400gr SKU → dona-narx (kg-narx EMAS; 2.5× shishish yo'qligini pin qiladi).
2. Yarim-tayyor rekursiv: semi retsepti orqali (saqlangan buzuq pp'ga emas).
3. `_update_output_cost_and_price`: pp == uzatilgan `cost_per_unit` (weighted-avg yo'q); old_pp ataylab buzuq qiymatga qo'yilib chaqirilsa ham natija `cost_per_unit`ga teng.
3b. **Bir xil cost 2-marta → pp o'zgarmaydi, 2-history yo'q** (no-op, feedback-rekursiya o'lgani).
3c. **KRITIK regressiya fence:** turli cost bilan 2-marta (15000 keyin 18000, masalan bekor→qayta-tasdiq) → pp=18000, **2 ta `ProductPriceHistory` qatori, distinct doc_number, IntegrityError YO'Q**. (Eski spec bu yerda UNIQUE buzilardi.)
4. `cost <= 0` → pp o'zgarmaydi.
5. Har real o'zgarish `ProductPriceHistory` qatori yozadi (`doc_number` `PRC-` bilan boshlanadi); o'zgarmasa yozmaydi.
6. `cost > sale_price` → warning log, production bloklanmaydi (normal qaytadi).
7. Backfill: dry-run hech narsa yozmaydi (pp o'zgarmas, 0 history); apply per-unit (kg-narx emas).
7b. **KRITIK fence (C1 v2):** `FIN → MID (type='tayyor', o'z aktiv retsepti bor) → raw` zanjiri. (a) BITTA `run(apply=True)` → FIN ham, MID ham to'g'ri narxga keladi (own fixed-point bir o'tishda hal qiladi — own-cost MID'ni saqlangan buzuq pp'dan emas, MID retseptidan rekursiv hisoblaydi); (b) 2-marta `run(apply=True)` → 0 yangi `ProductPriceHistory`, narxlar o'zgarmaydi (idempotent). Bu fixture joriy two-phase-only kodda YIQILADI (FIN 1-o'tishda buzuq qoladi) — own fixed-point bilan o'tadi. Eski yarim_tayyor-only fixture C1'ni fence qilmaydi (semi sub-recipe rekursiyaga tushib ketadi).

## 6. Deploy (birlashgan, tungi oyna)

| Qadam | Tafsilot |
|---|---|
| Branch | `safe-fix-purchase-price` ← `feat-bulk-dispatch` |
| Backup | git tag `pre-purchase-price-YYYYMMDD` + DB dump (mutatsiya — majburiy) |
| Env | I1 BARTARAF: C1-v2 fix `app.routes.production` import'ini olib tashladi (own-cost mustaqil) → skript `SECRET_KEY`siz ishlaydi, auth-stack import yo'q. Qo'shimcha env qadam shart emas. |
| Pre | server2220'da DRY-RUN → 166 `old→new` + `ANOMALY`(>sale) + `SUSPECT`(|Δ|>70%) ko'rib chiqiladi. **M1 operator qadami:** `ANOMALY`/`SUSPECT` ichida **retseptsiz yarim-tayyor** (aktiv retsepti yo'q) buzuq pp'li bo'lsa — fixed-point uni tuzata olmaydi (jonli modeldan meros), uni qo'lda ko'rib tasdiqlash/tuzatish. Anomaliya/suspect ko'p → TO'XTA, avval xom ashyo/retseptsiz-semi narxi tuzatiladi |
| Deploy | merge → **server2220 konsolida** (ELYOR'dan emas) `cd /d D:\TOTLI BI` → taskkill → start.bat |
| Backfill | server2220'da `--apply` (bitta tranzaksiya) |
| Post | sold-products: produced mahsulot soxta zarari yo'qoldi; MAYDA PISTA 1kg/KITOB 1 musbat marja; 3-4 spot-check; `10.243.165.156:8080` (127.0.0.1 emas) |
| Rollback | Kod: `git revert`. Ma'lumot: `BACKFILL-` tarix qatorlaridan `old_purchase_price` tiklash skripti yoki DB dump restore. Idempotent → qayta yuritish xavfsiz |

## 7. Scope tashqarisi (ataylab)

- Xom ashyo (raw) `purchase_price` audit — Purchase hujjatlaridan keladi, ishonchli; DRY-RUN anomaliyasi belgilasa alohida ko'riladi. Bu spec'da to'liq audit qilinmaydi.
- `document_service.py` / `info.py` / `qoldiqlar.py` / `warehouse.py` dagi boshqa `purchase_price=` yo'llari — production rollup bug'i emas, tegilmaydi.
- sales-metrics worktree tozalash — alohida.
- **M1 qoldiq xavf (ataylab, fenced):** aktiv retseptsiz `yarim_tayyor` buzuq saqlangan pp bilan — fixed-point yetib bormaydi (jonli model production.py:88-93 ham shunday meros). Chegaralangan, `ANOMALY`/`SUSPECT` DRY-RUN'da ko'rsatadi, operator §6 Pre'da qo'lda vetting qiladi. Kod o'zgarmaydi (xavfsizlik uchun shart emas).
- **M2 (minor, ixtiyoriy):** retsept tsikli `new=0` → hozir `SKIP(retsept bo'sh)` deb belgilanadi (texnik noaniq, lekin yozilmaydi → xavfsiz). Alohida `CYCLE` flag diagnostikani yaxshilardi; hozir kerak emas.
