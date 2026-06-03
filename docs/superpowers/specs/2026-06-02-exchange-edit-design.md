# Exchange (almashtirish) Tahrirlash — Dizayn

**Sana:** 2026-06-02
**Talab:** `project_exchange_edit_feature_request_20260602` — admin istalgan vaqt agent exchange'ni tahrirlay olsin.
**Qamrov:** YETKAZILMAGAN exchange (status draft/confirmed, stock harakatsiz). Yetkazilgan — ALOHIDA keyin.

---

## Muammo
Agent almashtirish (AGT exchange: return_sale parent + child sale) yaratilgach, web'da **tahrirlash UI yo'q** (`/sales/exchange/{id}` faqat ko'rish). Agent xato qilsa yoki admin qarori o'zgarsa (masalan "malina o'rniga boshqa narsa"), admin o'zgartira olmaydi.

## Qarorlar (brainstorming)
| Savol | Qaror |
|-------|-------|
| Qamrov | Yetkazilmagan (draft/confirmed, stock harakatsiz) |
| Workflow | To'g'ridan-to'g'ri "Tahrirlash" tugmasi (revert shart emas) |
| Tahrir | Ikkala yarmini (qaytarish + yangi sotuv) itemlari erkin |
| Balans | recompute (#3) avtomatik — farq partner balansiga |

## Asosiy fakt
- Exchange: `return_sale` (parent, parent_order_id=NULL, Vozvrat ombori) + `sale` (child, parent_order_id=parent.id, agent ombori).
- `OrderItem`: order_id, product_id, quantity, price, discount_percent, total.
- **Stock confirm'da harakatlanmaydi** (yetkazishda) → yetkazilmagan exchange itemlarini tahrirlash xavfsiz (faqat order_items + total + balans).

---

## Arxitektura

### 1. UI
- `templates/sales/exchange_detail.html` ga **"Tahrirlash"** tugmasi — faqat: parent.status IN ('draft','confirmed') VA ikkala order'da stock_movement yo'q VA user admin/manager.
- Yangi `templates/sales/exchange_edit.html`: forma — 2 jadval:
  - **Qaytarish (parent return_sale)** itemlari: mahsulot select + miqdor + narx, qator qo'shish/o'chirish (JS)
  - **Yangi sotuv (child sale)** itemlari: shu kabi
  - Pastda jonli: qaytarish jami, yangi jami, balans farqi
  - Saqlash tugmasi

### 2. Backend (`app/routes/sales.py`)
**GET `/sales/exchange/{id}/edit`** — `sales_exchange_edit`:
- parent (return_sale, id yoki parent_order_id orqali) + child (parent_order_id==parent.id, type='sale') yuklash
- Yetkazilmaganlikni tekshirish (aks holda detail'ga redirect + xabar)
- products (is_active), template render

**POST `/sales/exchange/{id}/update`** — `sales_exchange_update`:
- Auth admin/manager
- Yetkazilmaganlikni QAYTA tekshirish (stock_movement yo'q, status delivered/completed emas) — aks holda rad
- Form: `ret_product_id[]`, `ret_quantity[]`, `ret_price[]`, `new_product_id[]`, `new_quantity[]`, `new_price[]`
- Har order uchun: eski `OrderItem`'larni o'chir, formadan yangi itemlar qo'sh, `subtotal`/`total` qayta hisoblash.
  - ⚠️ MUHIM: `compute_partner_balance` **`Order.total`** ishlatadi (sale +total, return_sale −total), `debt` EMAS. Shuning uchun ikkala order'da `total = Σ(qty×price)` TO'G'RI o'rnatilishi shart.
  - `subtotal = total` (chegirmasiz, agent exchange'da discount yo'q). `paid`/`debt`: mavjud yaratish defaultlariga mos (return paid=0/debt=0; sale paid=0/debt=total) — balansga ta'sir qilmaydi (recompute total bilan).
- `db.flush()` → `recompute_partner_balance(db, partner_id, reason="exchange_edit")`
- Holat saqlanadi (o'zgartirmaymiz)
- Redirect → `/sales/exchange/{parent.id}?edited=1`

### 3. Stock / Balans
- Stock TEGILMAYDI (yetkazishdan oldin). Yetkazilganda tahrirlangan itemlar bo'yicha harakatlanadi.
- Balans: return −total, sale +total → recompute net. Teng bo'lmasa farq partner balansiga.

---

## Fayl tuzilishi
| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/routes/sales.py` | exchange_edit (GET) + exchange_update (POST) | Modify |
| `templates/sales/exchange_detail.html` | "Tahrirlash" tugma | Modify |
| `templates/sales/exchange_edit.html` | tahrir forma (2 jadval + JS) | YANGI |
| `tests/test_exchange_edit.py` | unit/integ | YANGI |

## Testlar (TDD)
1. **update itemlarni almashtiradi:** yangi sotuv itemlari o'zgaradi (malina→boshqa), order_items yangilanadi, total to'g'ri
2. **balans:** teng exchange (yangi=qaytarish) → balans 0; teng bo'lmagan → farq partner balansiga (recompute)
3. **yetkazilgan rad:** stock_movement bor exchange → update rad (xabar)
4. **status saqlanadi:** confirmed exchange tahrir qilingach confirmed qoladi
5. **validatsiya:** bo'sh/noto'g'ri item rad

## Error handling
- Yetkazilgan (stock harakatlangan) → rad + "Yetkazilgan almashtirishni tahrirlab bo'lmaydi"
- Parent/child topilmasa → 404
- Item bo'sh → "Kamida bitta mahsulot" / qatorni o'tkazib yuborish

## Rollout
- Tungi oyna, backup, smoke. Subagent-driven, TDD.
- olcha (id=63/64) birinchi real test — malina o'rniga boshqa mahsulot.
- Rollback: backup + git revert.

## Qamrovdan tashqari (keyin)
- Yetkazilgan exchange tahriri (stock reversal)
- POS exchange (agar boshqa flow bo'lsa) — shu UI umumiy bo'lsa qamraydi
