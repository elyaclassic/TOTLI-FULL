"""Mavjud sof POS qaytarishlar uchun yetishmayotgan refund Payment'ni yozadi.
Default DRY-RUN. --apply bilan yozadi (backup oling!).
"""
import os, sys
os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from app.models.database import SessionLocal, Order, Payment
from app.services.refund_service import compute_return_refund
from app.services.finance_service import sync_cash_balance
from app.services.partner_balance_service import recompute_partner_balance

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    try:
        rets = db.query(Order).filter(Order.type == "return_sale",
                                      Order.status.notin_(["cancelled", "draft"])).all()
        plan = []
        for r in rets:
            if db.query(Order.id).filter(Order.parent_order_id == r.id).first():
                continue  # exchange
            if db.query(Payment.id).filter(Payment.order_id == r.id, Payment.category == "sale_return").first():
                continue  # allaqachon refund bor
            sale = None
            note = (r.note or "")
            for tok in note.replace(":", " ").replace("->", " ").split():
                if tok.startswith(("S-", "AGT-")):
                    sale = db.query(Order).filter(Order.number == tok, Order.type == "sale").first()
                    if sale:
                        break
            if not sale:
                print(f"  {r.number}: original sotuv topilmadi (note={note!r}) — o'tkazildi")
                continue
            lines = [(it.product_id, it.quantity) for it in r.items]
            info = compute_return_refund(db, sale, lines)
            if info["refund_cash"] > 0 and info["refund_cash_register_id"]:
                plan.append((r, sale, info))
        print("=" * 80)
        print(f"RETURN REFUND BACKFILL — {'APPLY' if APPLY else 'DRY-RUN'} | {len(plan)} ta")
        for r, sale, info in plan:
            print(f"  {r.number} (sotuv {sale.number}): refund {info['refund_cash']:,.0f} kassa#{info['refund_cash_register_id']}")
        if APPLY:
            for r, sale, info in plan:
                _today = datetime.now().strftime('%Y%m%d')
                _last = db.query(Payment).filter(Payment.number.like(f"PAY-{_today}-%")).order_by(Payment.number.desc()).first()
                _seq = (int(_last.number.split("-")[-1]) + 1) if (_last and _last.number) else 1
                db.add(Payment(number=f"PAY-{_today}-{_seq:04d}", date=datetime.now(), type="expense",
                               category="sale_return", payment_type="cash", status="confirmed",
                               partner_id=sale.partner_id, order_id=r.id,
                               cash_register_id=info["refund_cash_register_id"], amount=info["refund_cash"],
                               description=f"Qaytarish refund (backfill): {r.number} ({sale.number})"))
                db.flush()
                sync_cash_balance(db, info["refund_cash_register_id"])
                if sale.partner_id:
                    recompute_partner_balance(db, sale.partner_id, reason="sale_return_refund_backfill", ref=r.number)
            db.commit()
            print(f"\n[APPLIED] {len(plan)} refund yozildi.")
        else:
            print("\n[DRY-RUN] Hech narsa yozilmadi.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
