"""M1/M3 backfill — mavjud avans/agent-payment yozuvlariga payment_id FK to'ldirish.

Tungi deploy'da bir marta ishlatiladi (ensure_*_column ustun qo'shgandan KEYIN).
Default DRY-RUN (faqat hisobot). Qo'llash: --apply.

  python scripts/backfill_payment_links.py            # dry-run
  python scripts/backfill_payment_links.py --apply     # yozadi

M1 (EmployeeAdvance): fuzzy (kassa + "Avans: {ism}" + summa + sana) bilan eng mos
   confirmed (bo'lmasa cancelled) expense Payment. Ambiguous (2+ confirmed) -> LOG, skip.
M3 (AgentPayment): description'dagi "[AP#{id}]" marker bilan ANIQ (category=agent_collection).
"""
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

APPLY = "--apply" in sys.argv

from sqlalchemy import func
from app.models.database import SessionLocal, EmployeeAdvance, AgentPayment, Payment, Employee


def backfill_advances(db):
    rows = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.confirmed_at.isnot(None),
        EmployeeAdvance.payment_id.is_(None),
        EmployeeAdvance.cash_register_id.isnot(None),
    ).all()
    linked = ambiguous = notfound = 0
    for adv in rows:
        emp = db.query(Employee).filter(Employee.id == adv.employee_id).first()
        emp_name = ((emp.full_name if emp else None) or f"Xodim {adv.employee_id}")[:100]
        base = [
            Payment.cash_register_id == adv.cash_register_id,
            Payment.description == f"Avans: {emp_name}",
            Payment.amount == float(adv.amount or 0),
            func.date(Payment.date) == adv.advance_date,
            Payment.type == "expense",
        ]
        confirmed = db.query(Payment).filter(*base, Payment.status == "confirmed").all()
        cands = confirmed or db.query(Payment).filter(*base, Payment.status == "cancelled").all()
        if len(cands) == 1:
            adv.payment_id = cands[0].id
            linked += 1
        elif len(cands) > 1:
            ambiguous += 1
            print(f"  [AMBIGUOUS] advance#{adv.id} emp={emp_name} amount={adv.amount} "
                  f"date={adv.advance_date} -> {len(cands)} Payment: {[c.id for c in cands]}")
        else:
            notfound += 1
            print(f"  [NOTFOUND] advance#{adv.id} emp={emp_name} amount={adv.amount} date={adv.advance_date}")
    print(f"M1 advances: jami={len(rows)} linked={linked} ambiguous={ambiguous} notfound={notfound}")
    return linked


def backfill_agent_payments(db):
    rows = db.query(AgentPayment).filter(
        AgentPayment.status == "confirmed",
        AgentPayment.payment_id.is_(None),
    ).all()
    linked = ambiguous = notfound = 0
    for ap in rows:
        cands = db.query(Payment).filter(
            Payment.category == "agent_collection",
            Payment.description.like(f"%[AP#{ap.id}]%"),
        ).all()
        if len(cands) == 1:
            ap.payment_id = cands[0].id
            linked += 1
        elif len(cands) > 1:
            ambiguous += 1
            print(f"  [AMBIGUOUS] AP#{ap.id} -> {[c.id for c in cands]}")
        else:
            notfound += 1
            print(f"  [NOTFOUND] AP#{ap.id} partner={ap.partner_id} amount={ap.amount}")
    print(f"M3 agent_payments: jami={len(rows)} linked={linked} ambiguous={ambiguous} notfound={notfound}")
    return linked


def main():
    db = SessionLocal()
    try:
        print(f"=== Backfill payment_id FK ({'APPLY' if APPLY else 'DRY-RUN'}) {datetime.now()} ===")
        m1 = backfill_advances(db)
        m3 = backfill_agent_payments(db)
        if APPLY:
            db.commit()
            print(f"APPLIED: M1={m1} M3={m3} FK yozildi.")
        else:
            db.rollback()
            print(f"DRY-RUN: hech narsa yozilmadi (--apply bilan qo'llang). Bog'lanardi: M1={m1} M3={m3}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
