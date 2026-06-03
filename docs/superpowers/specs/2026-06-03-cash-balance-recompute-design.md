# Kassa balans recompute — Dizayn (2026-06-03)

## Maqsad

Kassa (CashRegister) balansini to'liq **"hujjatdan qayta hisoblash"** (recompute-from-documents) patterniga keltirish — bu pattern partner balans va stock uchun allaqachon joriy qilingan. Kassada drift hozir = 0, shu sababli bu **hardening + audit izi + monitoring**, "noldan qurish" emas.

## Joriy holat (mavjud infratuzilma)

- `app/services/finance_service.py:14` — `cash_balance_formula(db, cash_id, as_of_date=None)` — **kanonik formula**:
  `opening_balance + income - expense + transfer_in - transfer_out`. `(balans, income_sum, expense_sum)` qaytaradi.
- `app/services/finance_service.py:63` — `sync_cash_balance(db, cash_id)` — `cash.balance = cash_balance_formula(...)[0]`. POS to'lov, transfer, ops, advances'da **keng chaqiriladi**. `db.commit()` chaqirmaydi.
- Drift = 0 (sync hamma yo'llarda chaqiriladi).

## Yagona zaiflik: kassa hujjati (qoldiq) snapshot drift

`app/routes/qoldiqlar.py` kassa hujjati confirm (388-410) / revert (413-436) **snapshot-asosli**:

- **Confirm:** `item.previous_balance = cash.balance`; `target = current_balance + delta`;
  `cash.opening_balance = target - income_sum + expense_sum`; `cash.balance = target`.
- **Revert:** `target = item.previous_balance`; `cash.opening_balance = target - income_sum + expense_sum`; `cash.balance = target`.

**Bug:** agar confirm va revert orasida income/expense o'zgarsa (orqaga sanali yoki bekor qilingan to'lov), revert eski `target`ni **yangi** income/expense bilan qayta hisoblab `opening_balance`ni buzadi → doimiy drift `opening_balance` ichiga "pishib qoladi".

`previous_balance` (CashBalanceDocItem) **faqat** shu ikki joyda ishlatiladi (database.py:608). Boshqa `previous_balance`'lar KNT (691) va oylik (726) hujjatlari uchun — alohida.

## Yechim (4 o'zgarish)

### 1. `recompute_cash_balance(db, cash_id, *, reason, ref=None, actor=None)`

`finance_service.py`'ga yangi funksiya — `sync_cash_balance`ning audit-yozadigan ukasi (partner/stock pattern):

```python
def recompute_cash_balance(db, cash_id, *, reason, ref=None, actor=None) -> tuple:
    """Kassa balansini formuladan qayta hisoblab set qiladi + AuditLog yozadi.
    db.commit() CHAQIRMAYDI. Qaytaradi: (old_balance, new_balance)."""
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return (0.0, 0.0)
    old = float(cash.balance or 0)
    new, _, _ = cash_balance_formula(db, cash_id)
    cash.balance = new
    db.add(AuditLog(
        user_name=actor or "system",
        action="recompute",
        entity_type="cash_balance",
        entity_id=cash_id,
        entity_number=ref,
        details=f"reason={reason}; {old:.2f} -> {new:.2f}; delta={new - old:+.2f}",
    ))
    return (old, new)
```

**Audit hajmi qarori:** `sync_cash_balance` **jim qoladi** (har POS to'lov / transfer'da audit YO'Q — Payment/CashTransfer qatorining o'zi iz). `recompute_cash_balance` faqat **manual / hujjat / drift-fix** uchun audit yozadi. Bu audit_logs'ni POS shovqinidan himoya qiladi.

### 2. Kassa hujjati confirm/revert — opening-restore (snapshot drift fix)

Hujjatning haqiqiy vazifasi: `opening_balance`ni `delta`ga sozlash. Balans **doim formuladan** kelib chiqsin.

**Yangi ustun:** `CashBalanceDocItem.previous_opening` (Float, nullable) — confirm vaqtidagi eski `opening_balance`. `database.py` ORM + `ensure_*_column` migratsiya (ikkalasi birga — schema drift oldini olish).

- **Confirm (qoldiqlar.py:396-407):**
  ```python
  item.previous_balance = cash.balance        # display uchun (o'zgarmaydi)
  item.previous_opening = cash.opening_balance # revert uchun (yangi)
  delta = float(item.balance or 0)
  cash.opening_balance = float(cash.opening_balance or 0) + delta
  recompute_cash_balance(db, cash.id, reason="qoldiq_doc_confirm",
                         ref=doc.number, actor=current_user.username)
  ```
- **Revert (qoldiqlar.py:426-433):**
  ```python
  if cash and item.previous_opening is not None:
      cash.opening_balance = float(item.previous_opening)
      recompute_cash_balance(db, cash.id, reason="qoldiq_doc_revert",
                             ref=doc.number, actor=current_user.username)
  ```
  Fallback: eski hujjatlarda `previous_opening is None` bo'lsa, mavjud `previous_balance` mantiq saqlanadi (orqaga moslik).

Natija: `opening_balance` — hujjat tegadigan yagona maydon; `balance` — doim formuladan; revert income/expense churn'idan qat'i nazar aniq.

### 3. Drift monitorga kassa qo'shish

`scripts/recompute_drift_monitor.py` — partner+stock yoniga kassa bloki:
har `CashRegister` uchun `balance` vs `cash_balance_formula(db, c.id)[0]` solishtirish, `abs(farq) > 1.0` da drift ro'yxatiga qo'shish va Telegram alert (CLAUDE_BOT_TOKEN, OWNER_ID).

### 4. Verify skript

`C:\tools\check_cash_drift.py` — bir martalik tekshiruv (DRY-RUN), har kassa stored vs formula. Hozir 0 kutiladi (backfill kerak emas). `--apply` bilan `recompute_cash_balance(reason="manual_drift_fix")` chaqirib drift tuzatadi (backup oling).

## Test rejasi

- `recompute_cash_balance`: old→new qaytaradi, AuditLog yoziladi, commit chaqirmaydi.
- Kassa hujjati confirm → opening += delta, balans formuladan; revert → opening aniq tiklanadi.
- **Regression test (asosiy bug):** confirm → orasiga income qo'shish → revert → `opening_balance` confirm-oldi qiymatiga aniq qaytishi (income churn drift YO'Q).
- Drift monitor: sun'iy drift (`cash.balance += 999`) → alert ro'yxatida.

## Xavf va ehtiyot

- `sync_cash_balance` o'zgarmaydi (hot-path xavfsiz). Yangi `recompute_cash_balance` qo'shiladi.
- `ensure_*_column` pending tranzaksiya orasida chaqirilmasin ([[feedback-schema-migration-pattern]]).
- Deploy oldidan DB backup. Restart kerak (uvicorn --reload yo'q).
- Drift hozir 0 — data migratsiya yo'q, faqat kod.

## Bog'liq

- Partner: `app/services/partner_balance_service.py` (recompute_partner_balance pattern).
- Stock: `app/services/stock_service.py` (reconcile_stock pattern).
- Monitor: `scripts/recompute_drift_monitor.py` (partner+stock, kassa qo'shiladi).
