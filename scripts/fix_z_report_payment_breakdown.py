"""Z-hisobot payment_breakdown tuzatish skripti.

Barcha saqlangan Z-hisobot JSON fayllarida payment_breakdown ni
Order.payment_type o'rniga Payment jadvali + CashRegister orqali qayta hisoblaydi.
Split to'lovlar naqd/plastik/bank ga ajratiladi.

Ishlatish:
    python scripts/fix_z_report_payment_breakdown.py --dry-run   # faqat ko'rish
    python scripts/fix_z_report_payment_breakdown.py --apply     # saqlash
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Loyiha root'ini path ga qo'shish
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session
from app.models.database import SessionLocal, Order, Payment, CashRegister
from sqlalchemy import or_


def recalc_breakdown(db: Session, order_numbers: list[str]) -> list[dict]:
    if not order_numbers:
        return []

    orders = db.query(Order).filter(Order.number.in_(order_numbers)).all()
    order_ids = [o.id for o in orders]
    sales = [o for o in orders if (o.type or "sale") == "sale"]
    sale_ids = [o.id for o in sales]

    by_type: dict = {}
    sale_with_payments: set = set()

    if sale_ids:
        pmts = db.query(Payment).filter(
            Payment.type == "income",
            or_(Payment.status == "confirmed", Payment.status.is_(None)),
            Payment.order_id.in_(sale_ids),
        ).all()

        cash_pt_map = {
            c.id: (c.payment_type or "naqd").strip().lower()
            for c in db.query(CashRegister).all()
        }

        for p in pmts:
            sale_with_payments.add(p.order_id)
            pt = cash_pt_map.get(p.cash_register_id, "naqd")
            if pt == "perechisleniye":
                pt = "bank"
            if pt not in by_type:
                by_type[pt] = {"count": 0, "sum": 0.0}
            by_type[pt]["count"] += 1
            by_type[pt]["sum"] += float(p.amount or 0)

        qarz = [o for o in sales if o.id not in sale_with_payments]
        if qarz:
            by_type["qarz"] = {
                "count": len(qarz),
                "sum": sum(float(o.total or 0) for o in qarz),
            }

    return [
        {"type": k, "count": v["count"], "sum": v["sum"]}
        for k, v in sorted(by_type.items(), key=lambda x: -x[1]["sum"])
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()
    apply = args.apply

    z_root = ROOT / "data" / "z_reports"
    if not z_root.exists():
        print("data/z_reports papkasi topilmadi")
        return

    db: Session = SessionLocal()
    try:
        all_files = sorted(z_root.glob("*/*.json"))
        print(f"Topildi: {len(all_files)} ta Z-hisobot\n")

        for fpath in all_files:
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  SKIP {fpath.name}: o'qish xatosi — {e}")
                continue

            order_numbers = data.get("order_numbers", [])
            old_breakdown = data.get("payment_breakdown", [])

            # Faqat "split" bo'lganlarini tuzat
            has_split = any(
                (b.get("type") or "").lower() == "split" for b in old_breakdown
            )
            if not has_split:
                continue

            new_breakdown = recalc_breakdown(db, order_numbers)

            print(f"Z-ID: {data.get('z_id')}  ({fpath.parent.name})")
            print(f"  ESKI: {[(b['type'], b['sum']) for b in old_breakdown]}")
            print(f"  YANGI: {[(b['type'], b['sum']) for b in new_breakdown]}")

            if apply:
                data["payment_breakdown"] = new_breakdown
                fpath.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"  SAQLANDI OK")
            else:
                print(f"  (--apply bilan saqlash)")
            print()

        if not apply:
            print("\n--apply bilan qayta ishlatilsa o'zgarishlar saqlanadi.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
