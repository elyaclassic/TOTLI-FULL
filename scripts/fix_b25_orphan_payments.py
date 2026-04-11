"""
B2.5: Eski orphan sale payment'larni tozalash.

3 ta confirmed orphan payment:
  - PAY-20260311-0002 (id=24): Asosiy kassa plastik, 1,230,000 (01.03)
  - PAY-20260314-0024 (id=79): Do'kon 1 kassa, 282,000 (14.03)
  - PAY-20260314-0025 (id=80): Do'kon 1 kassa, 57,000 (14.03)

Harakat: status='confirmed' -> status='cancelled'
Natija: kassa balansi -1,569,000 so'm

AUDIT TRAIL: har payment uchun description'ga "[B2.5 CLEANUP 2026-04-11]" qo'shiladi
"""
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# Loyiha ildiziga chiqish
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv()

from app.models.database import SessionLocal, Payment, CashRegister
from app.routes.finance import _cash_balance_formula, _sync_cash_balance

TARGET_PAYMENT_IDS = [24, 79, 80]
CLEANUP_TAG = "[B2.5 CLEANUP 2026-04-11]"

db = SessionLocal()
try:
    # === 1. Payment'larni olish ===
    print("=== Hozirgi holat ===")
    payments = db.query(Payment).filter(Payment.id.in_(TARGET_PAYMENT_IDS)).all()
    cash_ids = set()
    total_amount = 0.0
    for p in payments:
        print(f"  ID={p.id}  {p.number}  {p.type}  {p.amount:,.0f}  status={p.status}  cash_id={p.cash_register_id}")
        cash_ids.add(p.cash_register_id)
        if p.status == "confirmed":
            total_amount += float(p.amount or 0)
    print(f"Jami confirmed summa: {total_amount:,.0f}")

    if len(payments) != 3:
        print(f"XATO: 3 ta payment kutilgan, topildi: {len(payments)}")
        sys.exit(1)

    if not all(p.status == "confirmed" for p in payments):
        print("XATO: hech qaysi payment confirmed emas, balki:")
        for p in payments:
            print(f"  id={p.id} status={p.status}")
        sys.exit(1)

    # === 2. Oldingi kassa balanslari ===
    print()
    print("=== Oldingi kassa balanslari ===")
    prev_balances = {}
    for cid in cash_ids:
        computed, _, _ = _cash_balance_formula(db, cid)
        cash = db.query(CashRegister).filter(CashRegister.id == cid).first()
        prev_balances[cid] = {
            "name": cash.name if cash else f"cash_{cid}",
            "stored": float(cash.balance or 0) if cash else 0.0,
            "computed": computed,
        }
        print(f"  [{cid}] {prev_balances[cid]['name']}: "
              f"stored={prev_balances[cid]['stored']:,.0f}  "
              f"computed={prev_balances[cid]['computed']:,.0f}")

    # === 3. Status o'zgartirish + description tag ===
    print()
    print("=== O'zgarishlar ===")
    for p in payments:
        old_desc = p.description or ""
        if CLEANUP_TAG not in old_desc:
            p.description = f"{CLEANUP_TAG} {old_desc}".strip()
        p.status = "cancelled"
        print(f"  ID={p.id}: confirmed -> cancelled  tag qo'shildi")

    # === 4. Flush (lekin commit emas) ===
    db.flush()

    # === 5. Kassa balansini qayta hisoblash va yangilash ===
    print()
    print("=== Yangi kassa balanslari ===")
    for cid in cash_ids:
        _sync_cash_balance(db, cid)
        computed, _, _ = _cash_balance_formula(db, cid)
        cash = db.query(CashRegister).filter(CashRegister.id == cid).first()
        diff = computed - prev_balances[cid]["computed"]
        print(f"  [{cid}] {prev_balances[cid]['name']}: "
              f"yangi={computed:,.0f}  farq={diff:+,.0f}")

    # === 6. Tasdiqlash ===
    print()
    total_diff = sum(
        (_cash_balance_formula(db, cid)[0] - prev_balances[cid]["computed"])
        for cid in cash_ids
    )
    print(f"Kutilgan jami farq: -{total_amount:,.0f}")
    print(f"Haqiqiy jami farq:  {total_diff:+,.0f}")

    if abs(abs(total_diff) - total_amount) > 0.5:
        print("XATO: farq kutilgan qiymat bilan mos emas! ROLLBACK.")
        db.rollback()
        sys.exit(1)

    # === 7. Commit ===
    db.commit()
    print()
    print("✓ O'zgarishlar saqlandi (commit)")
    print(f"✓ Backup: D:\\TOTLI_BI_BACKUPS\\live\\2026-04-11_15-42-55.db.gz")
    print(f"✓ Rollback: python scripts/restore_from_backup.py 2026-04-11_15-42-55.db.gz")

finally:
    db.close()
