# Spec: Payment allokatsiya / FK bog'lash (M1 + M2 + M3)

**Sana:** 2026-06-04
**Status:** TAYYOR — tungi deploy kutmoqda (schema o'zgarishi + ma'lumot migratsiyasi)
**Audit:** [[project-audit-findings-20260603]] M1, M2, M3 (MEDIUM)

## Muammo (umumiy sinf)

Uchchala topilma ham bir xil ildizdan: **Payment qaysi hujjat/operatsiyaga tegishli ekani aniq BOG'LANMAGAN**. Shu sababli o'chirish/revert fuzzy-match (ism+summa+sana) yoki noaniq (partner+amount+category) bo'yicha ishlaydi va noto'g'ri Payment'ni o'chirishi / drift berishi mumkin.

| # | Joy | Hozirgi (buggy) | Ta'sir |
|---|-----|-----------------|--------|
| M1 | employees_advances.py | Avans bekor/o'chirishda Payment fuzzy-match (ism+summa+sana) bo'yicha topiladi | Bir xil summa/sana/ismli boshqa Payment o'chishi mumkin |
| M3 | revert_agent_payment | Payment (partner, amount, category) bo'yicha o'chiriladi, AP-id emas | Noto'g'ri Payment + kassa drift |
| M2 | delivery_routes.py:1228-1244 | Confirm FIFO bir nechta orderga taqsimlaydi; revert/edit faqat p.order_id qaytaradi | Per-order debt drift (partner balansi TO'G'RI) |

## Yechim

### M1 + M3 — to'g'ridan-to'g'ri FK
1. **Schema:** `payments` jadvaliga nullable FK ustun(lar):
   - `advance_id INTEGER` (EmployeeAdvance.id ga) — M1
   - `agent_payment_id INTEGER` (AgentPayment.id ga) — M3
   - `ensure_*_column` pattern bilan (mavjud [[feedback-schema-migration-pattern]]: pending tranzaksiya orasida CHAQIRMA, db.rollback bor).
2. **Backfill (bir martalik skript):** mavjud avans/agent-payment uchun hozirgi fuzzy mantiq bilan eng yaxshi mos Payment topib `advance_id`/`agent_payment_id` to'ldirish. Noaniq qolганlarni LOG qilish (qo'lda ko'rib chiqish).
3. **Kod:** yaratishda FK yoziladi; o'chirish/revert FK bo'yicha (`Payment.advance_id == advance.id`), fuzzy fallback faqat FK NULL (eski) bo'lsa.
4. **ORM drift ogohlik** ([[feedback-orm-db-schema-drift]]): ensure_*_column DB'ga qo'shadi, ORM model'ga ham `advance_id = Column(...)` qo'shilsin (aks holda runtime AttributeError).

### M2 — allokatsiya yoki order-debt recompute
**Kontekst:** partner balansi (compute_partner_balance = Σorder.total − Σpayment) ALLAQACHON to'g'ri. Drift faqat `order.debt`/`order.paid` per-order ko'rsatkichida va kelajak FIFO-targeting'da.

Ikki variant:
- **A (yengilroq):** revert/edit'da p.order_id'ni qaytarib, so'ng partner'ning BARCHA sale orderlari `paid`/`debt`'ini confirmed payment'lardan FIFO bilan qayta-derive qiluvchi helper (`recompute_partner_order_debts(db, partner_id)`). Idempotent, allokatsiya jadvali shart emas. Confirm/revert/edit'da chaqiriladi.
- **B (to'liq):** `PaymentAllocation(payment_id, order_id, amount)` jadvali — confirm taqsimotni yozadi, revert/edit aynan teskari qaytaradi. Aniqroq lekin ko'proq schema.

**Tavsiya: Variant A** — drift ko'rsatkichda, balans emas; recompute pattern kodda allaqachon ishonchli ishlatiladi. Yangi jadval shart emas.

## Tungi deploy runbook
1. Backup: `totli_holva.db.bak_pre_payment_alloc_<sana>` (online backup).
2. Branch `fix-m1-m2-m3-payment-alloc`.
3. TDD: M1 FK-delete, M3 FK-revert, M2 recompute helper — har biri uchun test (mavjud test_medium_*.py pattern: helper'larni pure ajratib testlash).
4. ensure_*_column + ORM model ustunlari + backfill skript.
5. Backfill DRY-RUN (log) → ko'rib chiqish → apply.
6. To'liq suite (271+ passed bo'lsin, login flake mustasno).
7. Merge → push → foreground restart (taskkill + `tasklist /S` kill-tasdiq + schtasks /run + /login 200 + yangi PID) — [[reference-remote-restart-from-elyor]].
8. Post-smoke: avans bekor, agent-payment revert, driver payment edit (FIFO ko'p order) → drift yo'qligini tekshir.

## Bog'liq
[[project-medium-audit-progress-20260604]] · [[project-audit-findings-20260603]] · [[feedback-schema-migration-pattern]] · [[feedback-orm-db-schema-drift]]
