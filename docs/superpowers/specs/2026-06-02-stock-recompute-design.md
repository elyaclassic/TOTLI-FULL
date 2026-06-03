# Stock Recompute Pattern — Dizayn (Spec)

**Sana:** 2026-06-02
**Audit topilmasi:** #1 (stock drift). Ildiz-sabab tahlili: `project_stock_drift_rootcause_20260602`
**Bog'liq:** partner recompute pattern (`2026-06-01-partner-balance-recompute-design.md`) — shu pattern moslashtirilgan.

---

## Muammo
`stocks.quantity` (denormalizatsiyalangan kesh) `stock_movements` ledger'idan **desync** bo'lgan.
10 ta (wh, product) da stored > Σmovements (musbat drift, ~280 birlik).

**Ildiz-sabab (trace bilan tasdiqlangan):**
1. Bir (wh, product) uchun **bir nechta Stock row** — transfer'lar bir row'ga, QLD adjustment boshqasiga tushgan; `create_stock_movement` MERGE ularni birlashtirgan, lekin baseline desync qolgan.
2. **Ijro tartibi ≠ created_at tartibi** (back-dated transfer + keyin tasdiqlangan QLD).
3. `create_stock_movement` (stock_service.py:110) har doim `stock += change` qiladi — bu O(1) va to'g'ri; drift undan EMAS, edge-case'lardan.

**Ledger Σ = jismoniy haqiqat** (HOLVA BARGELI LIST: ledger 189.50 = QLD 235.65 − transfer 65 + production 18.85; stored 254.50 xato).

## Qarorlar (brainstorming)
| Savol | Qaror |
|-------|-------|
| Shakl | **A. Inkremental (O(1) yozuv) + reconcile + monitor** (partner "har yozuvda recompute" emas — stock yuqori-hajmli) |
| Reconcile triggerlari | Ombor transfer (confirm/revert/delete) + QLD/INV adjustment (confirm/revert) |
| Ko'p Stock row | Birlashtirib **(warehouse_id, product_id) unique constraint** |
| Data fix | **10 mahsulotning hammasi** ledger'dan rebuild (etiketka/idish ham — bu kesh-desync, consumption emas) |
| Monitor | Kunlik stored vs Σmovements + Telegram alert |

---

## Arxitektura

`app/services/stock_service.py` ga qo'shiladi (create_stock_movement yonida):

### 1. `compute_stock_quantity(db, warehouse_id, product_id) -> float`
Kanonik haqiqat: barcha movement'lar yig'indisi.
```python
def compute_stock_quantity(db, warehouse_id, product_id) -> float:
    return float(db.query(func.coalesce(func.sum(StockMovement.quantity_change), 0.0))
                 .filter(StockMovement.warehouse_id == warehouse_id,
                         StockMovement.product_id == product_id).scalar() or 0.0)
```

### 2. `reconcile_stock(db, warehouse_id, product_id, *, reason, actor=None) -> tuple`
- Dublikat Stock row'larni 1 ga birlashtiradi (mavjud merge mantiqi qayta ishlatiladi)
- `stock.quantity = compute_stock_quantity(...)`
- `AuditLog` yozadi (entity_type="stock", old/new/delta/reason)
- **commit qilmaydi** (chaqiruvchi tranzaksiyasi)
- `(old, new)` qaytaradi

### 3. Yozuv yo'li — O'ZGARMAYDI
`create_stock_movement` ning `stock += change` (O(1)) saqlanadi. Normal sotuv/production toza inkremental — tez.

### 4. Reconcile chaqiruv nuqtalari
| Fayl | Funksiya | Chaqiruv |
|------|----------|----------|
| `warehouse.py` | `warehouse_transfer_confirm` (623) | har item: reconcile(from_wh, pid) + reconcile(to_wh, pid) |
| `warehouse.py` | `warehouse_transfer_revert` (709) | shu kabi |
| `warehouse.py` | `warehouse_transfer_delete` (760) | movement o'chgach reconcile |
| `qoldiqlar.py` | QLD/INV `..._tasdiqlash` (1759 loop) | har item: reconcile(wh, pid) |
| `qoldiqlar.py` | QLD/INV revert | shu kabi |

Bulk: ta'sirlangan (wh,pid) to'plami yig'ilib, oxirida har biriga 1 marta reconcile.

### 5. Bitta Stock row (ildiz himoyasi)
- Bir martalik: barcha dublikat Stock row'larni birlashtirish (skript).
- `(warehouse_id, product_id)` ga **UNIQUE INDEX**. ⚠️ Mavjud dublikatlar bo'lsa CREATE UNIQUE INDEX XATO beradi — shuning uchun `ensure_stock_unique_index()` AVVAL dublikatlarni birlashtiradi (idempotent), KEYIN indexni yaratadi. Deploy'da `merge_duplicate_stocks.py` ham oldin yuriladi (ikki qavat himoya).
- Dublikat hech qachon paydo bo'lmaydi → merge desync imkonsiz.
- `create_stock_movement` dagi merge mantiqi safety-net sifatida qoladi (zararsiz).

### 6. Data fix (bir martalik)
`scripts/backfill_stock_quantities.py`: dry-run hisobot (wh, product, stored, computed, delta) → tasdiq → backup → apply (10 mahsulot, hammasi).

### 7. Drift monitor (Faza 0)
`scripts/stock_drift_monitor.py` (Task Scheduler, kunlik): barcha (wh,pid) stored vs compute; drift > 0.01 bo'lganlar Telegram'ga (Yordamchim) yuboriladi.

---

## Fayl tuzilishi
| Fayl | Mas'uliyat | Holat |
|------|-----------|-------|
| `app/services/stock_service.py` | compute + reconcile | Modify |
| `app/routes/warehouse.py` | transfer confirm/revert/delete → reconcile | Modify |
| `app/routes/qoldiqlar.py` | QLD/INV confirm/revert → reconcile | Modify |
| `app/models/database.py` | (wh,product) unique index ensure | Modify |
| `scripts/merge_duplicate_stocks.py` | dublikat row birlashtirish | YANGI |
| `scripts/backfill_stock_quantities.py` | data fix (dry-run/apply) | YANGI |
| `scripts/stock_drift_monitor.py` | kunlik monitor | YANGI |
| `tests/test_stock_reconcile.py` | unit + bug-repro | YANGI |

---

## Testlar (TDD)
1. **compute_stock_quantity** — turli movement kombinatsiyalari (kirim/chiqim/transfer/adjustment)
2. **reconcile_stock** — stored = Σmovements; dublikat row birlashadi; audit log yoziladi
3. **Idempotentlik** — reconcile 2 marta = bir xil
4. **🎯 Bug reproduksiyasi:** QLD adjustment + back-dated transfer (turli Stock row) → reconcile to'g'ri Σ ni beradi (drift 0)
5. **Transfer churn** — confirm→revert→confirm reconcile bilan drift 0
6. **Unique constraint** — bir (wh,product) ga 2-row qo'shilsa xato/birlashadi

## Error handling
- `compute` movement yo'q → 0.0
- reconcile'da Stock row yo'q → yangi row computed qiymat bilan
- Manfiy computed → WARNING log (jismoniy sanash kerak), lekin set qilinadi
- reconcile commit qilmaydi → operatsiya xato bo'lsa rollback (atomik)

## Rollout
- Tungi oyna, backup, smoke
- Ketma-ketlik: compute+reconcile servis+test → unique index (dublikat merge oldin) → reconcile chaqiruvlar (warehouse, qoldiqlar) → data fix (dry-run→tasdiq→apply 10 mahsulot) → monitor o'rnatish → restart → post-smoke
- Subagent-driven, har task TDD + review
- Rollback: DB backup + git revert

## Qamrovdan tashqari (kelajak)
- Kassa balans recompute (alohida)
- Etiketka NEGATIVE drift strategiyasi ([[etiketka-drift-strategy]]) — o'zgarmaydi (jismoniy sanash, INV movement orqali)
