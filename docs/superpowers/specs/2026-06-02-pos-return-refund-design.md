# POS Qaytarish Refund — Dizayn (Sub-1)

**Sana:** 2026-06-02
**Bug:** return-refund kassa bug. Root cause: `project_return_refund_bug_20260602`
**Qamrov:** POS standalone qaytarish (sales.py:3933 "Savdodan qaytarish"). Exchange (Sub-2) ALOHIDA.

---

## Muammo
POS qaytarish (return_sale) yaratilganda:
1. **Kassadan refund (chiqim) yaratilmaydi** → naqd sotuv qaytarilsa kassa xayoliy oshadi (0 ta refund tarixda).
2. Return total **item narxlaridan** olinadi (chegirmasiz) → 520k mahsulot 500k sotilgan bo'lsa return 520k bo'ladi (paid 500k EMAS).

## Qarorlar (brainstorming, tasdiqlangan)
| Savol | Qaror |
|-------|-------|
| Refund qoidasi | **To'langaniga qarab:** naqd sotuv → naqd refund; qarz sotuv → faqat qarz kamayadi (kassa tegilmaydi) |
| Refund summasi | `sale.paid × (qaytgan_qiymat / sale.subtotal)` — proporsional, chegirma avtomatik |
| Return total | Chegirmali qiymatga moslanadi (item narxi emas) → partner balans toza |
| Revert | Refund Payment o'chiriladi + kassa qayta sync |
| Exchange | child-sale'li return'ga refund YO'Q (guard) |
| Data fix | 2 mavjud sof qaytarish (S-0197 ~500k, R-0601 ~30k) |

---

## Arxitektura

### 1. Refund hisoblash — `app/services/refund_service.py` (YANGI)
`compute_return_refund(db, sale, returned_items) -> dict`:
```
returned_value = Σ(returned_qty[i] × sale_item.price[i])   # item narxlarida
ratio = returned_value / sale.subtotal   (sale.subtotal>0; aks holda 0)
# Sotuvning NAQD income to'lovlari (cash/naqd payment_type)
cash_paid = Σ(sale ning income Payment.amount WHERE payment_type IN ('cash','naqd'))
refund_cash = round(cash_paid × ratio, 2)
# Return total — chegirmali (sale.total proporsional)
return_total = round(float(sale.total or 0) × ratio, 2)
# Refund kassasi — sotuvning eng katta naqd income to'lovi kassasi
refund_cash_register_id = <sale ning eng katta cash income Payment.cash_register_id>
qaytaradi: {refund_cash, return_total, refund_cash_register_id, ratio}
```
Qarz sotuv (cash_paid=0) → refund_cash=0 (kassa tegilmaydi).

### 2. Return yaratish — `sales.py:3933` migratsiya
- `compute_return_refund` chaqiriladi.
- `return_order.total = return_total`, `return_order.paid = return_total` (chegirmali; item-price line totals item displayda qoladi).
- `refund_cash > 0` bo'lsa: `Payment(type="expense", category="sale_return", partner_id=sale.partner_id, cash_register_id=refund_cash_register_id, order_id=return_order.id, amount=refund_cash, payment_type="cash", status="confirmed", number=<PAY-...>, date=now)` qo'shiladi + `sync_cash_balance(db, refund_cash_register_id)`.
- Exchange guard: agar bu return'ning child sale'i bo'lsa (`Order.parent_order_id == return.id` mavjud) — refund O'TKAZIB YUBORILADI.

### 3. Return revert — `sales.py:4018` migratsiya
- Mavjud stock-revert (−qty) saqlanadi.
- Shu return'ning refund Payment'i (category="sale_return", order_id=doc.id) **o'chiriladi** (`db.delete`) + `sync_cash_balance` + recompute_partner_balance.
- `doc.status = "cancelled"`.

### 3b. Z-hisobot naqd hisobi — `z_cash_summary.py` (MUHIM)
`compute_z_cash_summary` faqat `category IN ('expense','expense_doc','other')` (harajat) va `'supplier_payment'` ni naqd chiqim sanaydi. Refund `category='sale_return'` qo'shilmasa Z-hisobot naqd baribir oshiq qoladi. **Fix:** `cash_expenses_total` (yoki yangi `cash_refunds`) filtriga `'sale_return'` qo'shilsin (faqat naqd payment_type). Shunda smena Z naqdidan refund ayriladi.

### 4. Data fix — `scripts/backfill_return_refunds.py` (YANGI)
Mavjud sof qaytarishlar (return_sale, child-sale'siz, naqd sotuvdan): note'dan original sotuvni topib, `compute_return_refund` bo'yicha refund Payment yozadi. Dry-run → tasdiq → apply (backup bilan). 2 ta: S-0197 (~500k), R-0601 (~30k).

---

## Fayl tuzilishi
| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/services/refund_service.py` | compute_return_refund | YANGI |
| `app/routes/sales.py` | return yaratish (3933) + revert (4018) refund | Modify |
| `app/utils/z_cash_summary.py` | refund (sale_return) naqd chiqim hisobga olinsin | Modify |
| `scripts/backfill_return_refunds.py` | data fix (dry-run/apply) | YANGI |
| `tests/test_return_refund.py` | unit + integ | YANGI |

## Testlar (TDD)
1. **compute_return_refund:** to'liq naqd qaytarish → refund=sale.paid; qisman → proporsional; chegirmali (520k/500k) → refund=500k×ratio; qarz sotuv → refund=0
2. **Return yaratish:** naqd sotuv qaytarilsa expense Payment(sale_return) yaratiladi, summa to'g'ri; qarz sotuv → Payment yo'q
3. **Exchange guard:** child-sale'li return → refund yo'q
4. **Revert:** refund Payment o'chadi, kassa qaytadi
5. **Partner balans:** return_total chegirmali → naqd customer balans toza (0)

## Error handling
- `sale.subtotal <= 0` → ratio=0, refund=0 (log warning)
- Sotuvda naqd income yo'q (qarz) → refund_cash=0 (normal)
- Refund kassasi topilmasa → refund yozilmaydi + log warning (qo'lda tekshirilsin)

## Rollout
- Tungi oyna, backup, smoke
- Ketma-ketlik: refund_service+test → return yaratish+revert migratsiya → data fix (dry-run→tasdiq→apply) → restart → post-smoke
- Subagent-driven, TDD
- Rollback: backup + git revert

## Qamrovdan tashqari (Sub-2, keyin)
- Agent exchange qaytarish (api_agent_ops, parent+child) revert/refund
- `/sales/{id}/revert` ni return_sale uchun kengaytirish (yoki UI to'g'ri tugmaga yo'naltirish)
