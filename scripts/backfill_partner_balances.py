"""Barcha partner balansini hujjatlardan qayta quradi (recompute pattern).

Default: DRY-RUN (faqat hisobot, hech narsa yozilmaydi).
--apply bilan yozadi (AVVAL backup oling!).

Ishlatish:
    python scripts/backfill_partner_balances.py            # dry-run hisobot
    python scripts/backfill_partner_balances.py --apply    # yozadi (backup kerak)
"""
import os
import sys

os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
sys.path.insert(0, r"\\server2220\d\TOTLI BI")
sys.stdout.reconfigure(encoding="utf-8")

from app.models.database import SessionLocal, Partner
from app.services.partner_balance_service import (
    compute_partner_balance,
    recompute_partner_balance,
)

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    try:
        partners = db.query(Partner).order_by(Partner.id).all()
        changes = []
        for p in partners:
            stored = float(p.balance or 0)
            computed = compute_partner_balance(db, p.id)
            if abs(stored - computed) > 0.01:
                changes.append((p.id, p.name, p.is_active, stored, computed, computed - stored))
        changes.sort(key=lambda x: abs(x[5]), reverse=True)
        print("=" * 92)
        print(f"PARTNER BALANS BACKFILL — {'APPLY' if APPLY else 'DRY-RUN'}")
        print("=" * 92)
        print(f"Jami partner: {len(partners)} | o'zgaradigan: {len(changes)}")
        print(f"{'id':<6}{'nom':<30}{'akt':<5}{'stored':>15}{'computed':>15}{'delta':>15}")
        print("-" * 92)
        for pid, name, active, s, c, d in changes:
            print(f"{pid:<6}{(name or '')[:29]:<30}{('ha' if active else 'yo'):<5}{s:>15,.0f}{c:>15,.0f}{d:>+15,.0f}")
        print("-" * 92)
        pos = sum(d for *_, d in changes if d > 0)
        neg = sum(d for *_, d in changes if d < 0)
        print(f"Jami delta (abs): {sum(abs(x[5]) for x in changes):,.0f}  | musbat: {pos:,.0f}  manfiy: {neg:,.0f}")
        if APPLY:
            for pid, *_ in changes:
                recompute_partner_balance(db, pid, reason="backfill_recompute")
            db.commit()
            print(f"\n[APPLIED] {len(changes)} partner balansi yozildi.")
        else:
            print("\n[DRY-RUN] Hech narsa yozilmadi. --apply uchun avval backup oling.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
