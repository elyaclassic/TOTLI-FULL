# Partner Balans Recompute Pattern — Dizayn (Spec)

**Sana:** 2026-06-01
**Muallif:** Claude + Elyor (brainstorming)
**Audit topilmasi:** #3 (asl ildiz), #7/#8 (USD konvertatsiya) — `project_audit_freshdb_20260601`

---

## Muammo

`partner.balance` (denormalizatsiyalangan kesh) **25 ta joyda, 7 faylda** qo'lda
(`+=`/`-=`/snapshot) yangilanadi. Har biri o'z delta'sini mustaqil hisoblaydi.
Reconciliation (hujjatlardan hisoblangan haqiqat) bilan mos kelmaydi → **drift**.

Toza DB day-1'da drift qaytdi (4 partner, ~3M). Bu — inkremental keshning ildiz kasalligi.
Aynan shu kasallik kassa (revert bug) va stock (transfer sync)'da ham bor.

## Maqsad

`partner.balance` ni **inkremental mutatsiya** o'rniga **manba-hujjatlardan qayta quriladigan kesh**
ga aylantirish. Drift konstruksiya bo'yicha imkonsiz bo'lsin. Pattern keyin kassa/stock'ga ko'chirilsin.

## Qarorlar (brainstorming)

| Savol | Qaror |
|-------|-------|
| Qamrov | Umumiy qayta ishlatiladigan pattern (avval partner; kassa/stock keyin) |
| Yondashuv | **A. Recompute-from-documents** (absolyut set, self-healing) |
| USD konvertatsiya (#7/#8) | **Shu formulaga qo'shiladi** |
| Backfill | **Hammasini bir marta qayta qur** (backup + dry-run hisobot + tasdiq) |

---

## Arxitektura

Yangi servis: `app/services/partner_balance_service.py`

### 1. Kanonik formula — yagona haqiqat manbai

`compute_partner_balance(db, partner_id) -> float`

```
balance =  Σ sotuv.total                 # Order.type='sale'           → +
         − Σ qaytarish.total             # Order.type='return_sale'    → −
         − Σ to'lov_kirim.amount_uzs     # Payment.type='income'       → −
         + Σ to'lov_chiqim.amount_uzs    # Payment.type='expense'      → +
         − Σ xarid.(total+total_expenses)# Purchase confirmed          → −
         + Σ qoldiq_hujjat.balance       # PartnerBalanceDocItem (signed) → ±
         + Σ xarid_qaytarish.total       # PurchaseReturn confirmed    → +
```

**Filtrlar (reconciliation bilan AYNAN bir xil):**
- Orders: `type IN ('sale','return_sale')`, `status NOT IN ('cancelled','draft')`
- Payments: `partner_id` mos, `status='confirmed' OR status IS NULL`
- Purchases: `status='confirmed'`
- PartnerBalanceDocItem: `doc.status='confirmed'`
- PurchaseReturn: `status='confirmed'`

**Belgi konvensiyasi:** musbat = mijoz bizga qarzdor; manfiy = biz partnerga qarzdormiz.
(Mavjud `partner.balance` konvensiyasiga mos: sotuv +, xarid −, kirim −, chiqim +.)

**Valyuta (#7/#8):** har to'lov uchun
```python
amount_uzs = amount
cr = payment.cash_register
if cr and (cr.currency or 'UZS') != 'UZS':
    rate = get_rate(db, cr.currency, 'UZS', payment.date)  # currency_service
    amount_uzs = amount * rate
```
(`payments` jadvalida konvertatsiya maydoni yo'q → sana bo'yicha kurs olinadi.)

### 2. Display = kesh birlashtirish

`reports.py:_build_partner_movements` yopilish balansi shu summani ishlatsin (yoki
umumiy yordamchi orqali) — **display === stored kafolatlanadi**. USD konvertatsiya
shu yerda ham qo'llanadi (display ham to'g'rilanadi).

### 3. Persist + audit

`recompute_partner_balance(db, partner_id, *, reason, ref=None, actor=None) -> tuple[float,float]`
- `old = partner.balance`; `new = compute_partner_balance(...)`; `partner.balance = new`
- `audit_logs` ga yozadi: partner_id, old, new, delta, reason, ref (hujjat raqami/id), actor (user)
- **`db.commit()` chaqirmaydi** — chaqiruvchining tranzaksiyasiga qo'shiladi (atomik)
- `(old, new)` qaytaradi

### 4. Chaqiruv joylari — 25 mutatsiya almashtiriladi

Har joy: hujjat o'zgarishini bajar → `db.flush()` → `recompute_partner_balance(db, pid, reason=...)`.

| Fayl | Joy soni | reason |
|------|----------|--------|
| `app/routes/sales.py` | 5 | sale_confirm / sale_revert / sale_edit |
| `app/routes/delivery_routes.py` | 9 | delivery_deliver / agent_payment |
| `app/routes/qoldiqlar.py` | 4 | balance_doc_confirm / balance_doc_revert |
| `app/routes/finance.py` | 2 | payment_confirm / payment_revert |
| `app/services/document_service.py` | 2 | purchase_confirm / purchase_revert |
| `app/services/purchase_return_service.py` | 2 | purchase_return_confirm / cancel |
| `app/routes/api_driver_ops.py` | 1 | driver_deliver |

**Soddalashtirish:** `previous_partner_balance` / `previous_balance` snapshot mantiqi
**olib tashlanadi**. Revert = hujjatni `cancelled` qil → recompute (formula uni endi
hisobga olmaydi → balans avtomatik to'g'ri). Bu revert bug sinfini ham yo'qotadi.

**Bulk e'tibor:** ko'p qatorli operatsiyada (masalan 100 qatorli yetkazish) recompute
**partner bo'yicha 1 marta** chaqirilsin (loop ichida emas) — ta'sirlangan partner_id'lar
to'plami yig'ilib, oxirida har biriga 1 marta.

### 5. Backfill (bir martalik)

`scripts/backfill_partner_balances.py`:
1. Backup (`totli_holva.db.bak_pre_balance_backfill_<sana>`)
2. Har partner uchun `compute_partner_balance` → stored bilan solishtir
3. **Dry-run hisobot** (id, nom, stored, computed, delta) — faqat ko'rsatadi, yozmaydi
4. Foydalanuvchi tasdiqlagach: har partner.balance = computed, audit_log, commit
5. 4 driftli partner shunda tuzaladi

---

## Fayl tuzilishi

| Fayl | Mas'uliyat |
|------|-----------|
| `app/services/partner_balance_service.py` (YANGI) | compute + recompute + audit |
| `app/routes/reports.py` | `_build_partner_movements` kanonik summani ishlatsin |
| `app/routes/sales.py`, `delivery_routes.py`, `qoldiqlar.py`, `finance.py`, `api_driver_ops.py` | mutatsiya → recompute |
| `app/services/document_service.py`, `purchase_return_service.py` | mutatsiya → recompute |
| `scripts/backfill_partner_balances.py` (YANGI) | bir martalik backfill + dry-run |
| `tests/test_partner_balance_service.py` (YANGI) | unit + regressiya testlar |

---

## Testlar (TDD)

1. **compute — har hujjat turi:** sotuv → +total; qaytarish → −total; kirim → −amount;
   chiqim → +amount; xarid → −(total+exp); qoldiq doc → ±bal; xarid_qaytarish → +total
2. **USD to'lov:** USD kassadan $100 chiqim, kurs 12000 → balansga +1,200,000 (1,200,000, 100 emas)
3. **Filtrlar:** cancelled/draft hisobga olinmaydi; status=NULL to'lov hisobga olinadi
4. **Idempotentlik:** recompute 2 marta = bir xil natija
5. **confirm→revert→confirm:** balans boshlang'ich qiymatga qaytadi (drift yo'q)
6. **Regressiya:** `_build_partner_movements` yopilish balansi == `compute_partner_balance`
7. **Audit log:** recompute audit_logs ga 1 qator yozadi (old/new/delta/reason)

---

## Error handling

- `compute` partner topilmasa → 0.0 (reconciliation kabi)
- `get_rate(currency, 'UZS', sana)` xulq-atvori (aniq):
  1. Sanaga eng yaqin (`effective_date <= sana`) kursni qaytaradi (mavjud helper)
  2. Undan oldin kurs yo'q bo'lsa → keyingi eng yaqin (har qanday) kursni ishlat
  3. `exchange_rates` umuman bo'sh bo'lsa → konvertatsiya O'TKAZILMAYDI, xom amount
     ishlatiladi VA `WARNING` log yoziladi (admin kurs kiritishi shart). Bu holat
     faqat hech qanday kurs kiritilmagan tizimda bo'ladi; toza DB'da kurs (12000) bor.
- recompute commit qilmaydi → chaqiruvchi xato bo'lsa hammasi rollback (atomiklik)
- `actor` mavjud bo'lmagan joylarda (servislar) `None` — audit_log'da "system" deb yoziladi

## Rollout

- Tungi oyna (23:00+), backup, smoke (15 endpoint)
- Subagent-driven: har task implementer + spec review + code review
- Deploy ketma-ketlik: servis+test → call-site'lar (modulma-modul) → display birlashtirish →
  backfill (dry-run → tasdiq → apply) → restart → post-smoke
- Rollback: DB backup + git revert

## Qamrovdan tashqari (keyingi ishlar)

- Kassa balans recompute (shu pattern bilan) — alohida spec
- Stock balans recompute (transfer sync #1) — alohida spec
- Drift monitor (Faza 0) — kunlik stored vs compute solishtirish + alert
