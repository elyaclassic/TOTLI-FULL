# Yetkazib beruvchiga qaytarish (Purchase Return) — Dizayn spetsifikatsiyasi

**Sana:** 2026-05-31
**Holat:** Tasdiqlangan (brainstorming)
**Muallif:** Claude + Elyor

## 1. Maqsad va kontekst

Yetkazib beruvchidan olingan mahsulotni **brak / yaroqsiz / eskirgani** uchun
qaytarish kerak. Hozir tizimda bunday funksiya **yo'q**: `return_purchase` turi
faqat `Order.type` izohida (database.py:960) va bitta bot-hisobot filtrida
(report_queries.py:463) eslatilgan, lekin uni yaratadigan UI/route yo'q.

Vaqtinchalik yechimlar (Qoldiq tuzatish + balans hujjati alohida) drift xavfini
oshiradi (loyihada allaqachon 145 mijozda saqlangan-vs-hujjat balans drifti bor).
Shuning uchun **atomik, bitta hujjatli** to'g'ri funksiya quriladi.

**Qaror qilingan biznes parametrlari:**
- Pul hal: yetkazib beruvchi **qarzimizni kamaytiradi / kredit beradi** (naqd
  qaytarish yoki almashtirish emas — bu v1 ko'lamidan tashqarida).
- Hujjat turi: **mustaqil** (asl xaridga bog'lanmaydi).
- Narx: **tannarx avtomatik to'ldiriladi, tahrirlanadi.**

## 2. Ko'lam (scope)

**Kiradi (v1):**
- Yangi `PurchaseReturn` + `PurchaseReturnItem` modellari va jadvallari
- draft → confirmed → cancelled oqimi
- Tasdiqlashda atomik: stock chiqim + yetkazib beruvchi qarzini kamaytirish + audit
- Reconciliation hisobotiga integratsiya (DEBIT sifatida)
- UI: ro'yxat, yangi forma, detail/tasdiq/bekor

**Kirmaydi (v1, kelajakda):**
- Naqd pul qaytarish (Payment income bilan bog'lash)
- Yaxshi tovarga almashtirish (exchange)
- Asl xarid hujjatiga bog'lash / partiya kuzatuvi
- Write-off (kompensatsiyasiz zarar) — bu alohida stock adjustment bilan qilinadi

## 3. Data model

### `purchase_returns`
| Maydon | Tur | Izoh |
|---|---|---|
| id | Integer PK | |
| number | String(40) | `PR-YYYYMMDD-NNNN`, kunlik ketma-ketlik |
| date | DateTime | hujjat sanasi (vaqt-aware stock movement uchun) |
| partner_id | Integer FK→partners.id | yetkazib beruvchi |
| warehouse_id | Integer FK→warehouses.id | brak qaysi ombordan chiqadi |
| status | String(20) | `draft` / `confirmed` / `cancelled` (default `draft`) |
| reason | String(20) | `brak` / `expired` / `other` |
| total | Float | jami qiymat (= items.total yig'indisi) |
| notes | Text | izoh (ixtiyoriy) |
| user_id | Integer FK→users.id | yaratuvchi |
| created_at | DateTime | |

### `purchase_return_items`
| Maydon | Tur | Izoh |
|---|---|---|
| id | Integer PK | |
| return_id | Integer FK→purchase_returns.id | |
| product_id | Integer FK→products.id | |
| quantity | Float | qaytarilayotgan miqdor (> 0) |
| price | Float | tannarx (purchase_price'dan avtomatik, tahrirlanadi) |
| total | Float | quantity × price |

**Schema migration:** mavjud DB'ga jadval qo'shish uchun `ensure_*` helper
(`app/utils/db_schema.py` naqshi). Helper `db.rollback()` saqlanmasligi uchun
pending tranzaksiya orasida chaqirilmasin ([[schema-migration-pattern]]).
ORM model va DB ustunlari mos bo'lsin ([[orm-db-schema-drift]]).

## 4. Oqim va biznes mantig'i

### 4.1 Yaratish (`draft`)
Stock va balansga **ta'sir yo'q**. Forma saqlanadi, keyinroq tasdiqlanadi.

### 4.2 Tasdiqlash (`confirm`) — atomik, bitta commit
1. **Double-confirm himoyasi:** atomik `UPDATE purchase_returns SET status='confirmed'
   WHERE id=? AND status='draft'` — agar 0 qator o'zgarsa, allaqachon tasdiqlangan,
   to'xtatiladi ([[double-confirm-audit]]).
2. **Validatsiya** (commit oldidan):
   - Hujjatda kamida 1 qator bo'lsin
   - Har item: `quantity > 0`
   - Har item: ombordagi joriy qoldiq `>= quantity` (ko'p qaytarib bo'lmaydi)
   - Davr yopiq bo'lmasin (period-close tekshiruvi — mavjud naqsh)
3. **Har item uchun:**
   ```
   create_stock_movement(
       warehouse_id=doc.warehouse_id,
       product_id=item.product_id,
       quantity_change=-item.quantity,      # CHIQIM
       operation_type="return_purchase",
       document_type="PurchaseReturn",
       document_id=doc.id,
       document_number=doc.number,
       created_at=doc.date,                 # vaqt-aware
       note=f"Yetkazib beruvchiga qaytarish: {doc.number}",
   )
   ```
4. **Yetkazib beruvchi balansi:** `partner.balance += doc.total`
   (yetkazib beruvchi uchun `balance < 0` = biz qarzdormiz; `+=` qarzni kamaytiradi).
5. **`product.purchase_price` ga TEGILMAYDI** ([[purchase-price-corruption]]).
6. `log_action(action="confirm", entity_type="purchase_return", ...)`.
7. Yagona `db.commit()`; xatoda `db.rollback()` + DocumentError.

### 4.3 Bekor qilish (`cancel` / delete)
Tasdiqlangan hujjatni bekor qilish — to'liq teskari:
- Har item: `create_stock_movement(+quantity, operation_type="return_purchase_revert", ...)` → stock tiklanadi
- `partner.balance -= doc.total` → qarz tiklanadi
- status → `cancelled`, audit note
- Atomik, bitta commit.

## 5. Sign konvensiyasi (kritik — drift oldini olish)

| Operatsiya | Stock | partner.balance |
|---|---|---|
| Xarid tasdiq (mavjud) | `+qty` | `-= total` (qarz oshadi) |
| **Qaytarish tasdiq (yangi)** | `-qty` | `+= total` (qarz kamayadi) |
| Qaytarish bekor | `+qty` | `-= total` |

Tasdiqlash: `document_service.py` confirm naqshining aniq teskarisi.

## 6. Reconciliation integratsiyasi

`reports.py::_build_partner_movements` ga yangi blok (tasdiqlangan qaytarishlar):
```
doc_type = "Xarid qaytarish"
debit = doc.total        # xaridning teskarisi: yetkazib beruvchi kreditini kamaytiradi
credit = 0
doc_url = f"/purchase-returns/{doc.id}"
```
period_only va opening hisoblari mavjud naqshga mos. Bu integratsiya **majburiy** —
aks holda saqlangan balans (`balance += total`) va hujjat hisobi mos kelmaydi,
ya'ni funksiyaning o'zi drift yaratadi.

## 7. Validatsiya va xato holatlari

- Bo'sh hujjat → tasdiqlab bo'lmaydi (xato xabar)
- `quantity <= 0` → rad
- ombordagi qoldiq < quantity → rad ("Omborda yetarli emas: X mavjud, Y qaytarilmoqchi")
- yopiq davr → rad (`?error=period_closed`)
- double-confirm → atomik UPDATE bilan bloklanadi
- draft-lock: bir user uchun bitta ochiq qoralama ([[draft-lock-pattern]]); admin `force_new` bypass

## 8. UI

**Marshrutlar:**
- `GET /purchase-returns` — ro'yxat (number, sana, yetkazib beruvchi, jami, status)
- `GET /purchase-returns/new` — yangi forma
- `POST /purchase-returns` — qoralama yaratish
- `GET /purchase-returns/{id}` — detail
- `POST /purchase-returns/{id}/confirm` — tasdiqlash
- `POST /purchase-returns/{id}/cancel` — bekor qilish
- `GET /api/product-purchase-price?product_id=` — tannarxni avtomatik olish (forma uchun)

**Forma maydonlari:** yetkazib beruvchi (select), ombor (select), sana, mahsulot
qatorlari (mahsulot select → tannarx avtomatik to'ldiriladi → miqdor, narx
tahrirlanadi → qator jami), sabab (brak/expired/other), izoh. Tugmalar:
"Qoralama saqlash", "Tasdiqlash".

**Kirish:** admin/manager (xarid bilan bir xil rol).
**Navbar:** "Asosiy modullar" yoki "Xaridlar" yonida "Qaytarishlar" havolasi.
**"Orqaga" tugmasi:** rol asosida ([[back-button-role]]).

## 9. Test rejasi (TDD)

1. Tasdiqlash → har item bo'yicha stock `-qty`, `partner.balance += total`
2. Bekor → stock va balans aniq tiklanadi
3. Reconciliation → qaytarish DEBIT ("Xarid qaytarish") sifatida ko'rinadi, closing to'g'ri
4. Ombordagidan ko'p qaytarish → rad
5. Double-confirm → ikkinchi marta ta'sir qilmaydi
6. `product.purchase_price` o'zgarmaydi
7. Yopiq davr → tasdiqlab bo'lmaydi

## 10. Deploy

- **Tier B** (yangi jadval + yangi route; mavjud kodga minimal teginish:
  faqat `_build_partner_movements` ga additive blok + navbar havola).
- Backup oldin ([[live-backup]]), tungi oyna ([[safe-deployment]]).
- Smoke test (yangi endpointlar 200/303).
- `ensure_*` helper bilan jadval avtomatik yaratiladi (migration script shart emas).
- Rollback: yangi jadvallar additive, eski kod buzilmaydi; branch revert + restart.

## 11. Fayllar (taxminiy)

- `app/models/database.py` — `PurchaseReturn`, `PurchaseReturnItem` modellari
- `app/utils/db_schema.py` — `ensure_purchase_return_tables()` helper
- `app/services/document_service.py` yoki yangi `purchase_return_service.py` —
  confirm/cancel atomik mantiq
- `app/routes/purchase_returns.py` — yangi router (yangi fayl, izolyatsiya)
- `app/templates/purchase_returns/list.html`, `new.html`, `detail.html`
- `app/routes/reports.py::_build_partner_movements` — additive blok
- `app/main.py` — router registratsiya
- `app/templates/base.html` — navbar havola
- `tests/test_purchase_return.py` — testlar
