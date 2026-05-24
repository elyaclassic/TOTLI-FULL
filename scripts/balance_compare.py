r"""Sales Doctor balansy klientov XLSX ↔ TOTLI BI partnerlarni solishtirish.

Foydalanish (server'da):
    cd "D:\TOTLI BI"
    python scripts\balance_compare.py            # faqat hisobot (dry-run)
    python scripts\balance_compare.py --apply    # PartnerBalanceDoc yaratish (tasdiq so'raydi)

Solishtirish: nom (alfanumerik) yoki telefon (oxirgi 9 raqam) orqali.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models.database import SessionLocal, Partner, PartnerBalanceDoc, PartnerBalanceDocItem, User
from datetime import datetime

JSON_PATH = ROOT / "scripts" / "balance_import_20260520.json"


def norm_name(s: str) -> str:
    return "".join(c for c in (s or "").lower().strip() if c.isalnum())


def norm_phone(p: str) -> str:
    digits = "".join(c for c in (p or "") if c.isdigit())
    return digits[-9:] if len(digits) >= 7 else ""


def load_sd_rows():
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_db_indexes(db):
    partners = db.query(Partner).filter(Partner.is_active == True).all()
    by_name = {}
    by_phone = {}
    for p in partners:
        nk = norm_name(p.name)
        if nk:
            by_name.setdefault(nk, []).append(p)
        for ph in [p.phone, p.phone2]:
            pk = norm_phone(ph or "")
            if pk:
                by_phone.setdefault(pk, []).append(p)
    return partners, by_name, by_phone


def match_sd(sd, by_name, by_phone):
    candidates = []
    nk = norm_name(sd["name"])
    pk = norm_phone(sd["phone"])
    if nk in by_name:
        candidates.extend(by_name[nk])
    if pk and pk in by_phone:
        for c in by_phone[pk]:
            if c not in candidates:
                candidates.append(c)
    return candidates


def report():
    sd_rows = load_sd_rows()
    db = SessionLocal()
    try:
        partners, by_name, by_phone = build_db_indexes(db)
        print(f"Sales Doctor: {len(sd_rows)} mijoz | TOTLI BI: {len(partners)} aktiv mijoz")
        print()

        matched, multi, not_found = [], [], []
        for sd in sd_rows:
            cands = match_sd(sd, by_name, by_phone)
            if len(cands) == 1:
                matched.append((sd, cands[0]))
            elif len(cands) > 1:
                multi.append((sd, cands))
            else:
                not_found.append(sd)

        print(f"✓ Bir xil topildi: {len(matched)}")
        print(f"? Bir nechta variant: {len(multi)}")
        print(f"✗ Topilmadi: {len(not_found)}")
        print()

        # Farqi bo'lganlar
        diffs = [(sd, db_p, sd["summa"] - db_p.balance) for sd, db_p in matched if abs(sd["summa"] - db_p.balance) > 0.5]
        same = len(matched) - len(diffs)
        print(f"= Balans bir xil: {same}")
        print(f"≠ Balans farq qiladi: {len(diffs)}")
        print()

        if diffs:
            print("=" * 100)
            print(f"{'#':<3} {'TOTLI BI nomi':<32} {'Tel':<14} {'SD balans':>14} {'TOTLI balans':>14} {'Farq (delta)':>14}")
            print("-" * 100)
            for i, (sd, p, d) in enumerate(sorted(diffs, key=lambda x: abs(x[2]), reverse=True), 1):
                print(f"{i:<3} {(p.name or '-')[:32]:<32} {(p.phone or '-')[:14]:<14} {sd['summa']:>14,.0f} {p.balance:>14,.0f} {d:>14,.0f}")
            print("-" * 100)
            total_delta = sum(d for _, _, d in diffs)
            print(f"{'JAMI DELTA':<65} {total_delta:>14,.0f}")
            print()

        if not_found:
            print("=" * 80)
            print(f"TOPILMADI ({len(not_found)} ta):")
            for nf in not_found:
                print(f"  • {nf['name'][:40]:<40} phone={nf['phone']:<14} bal={nf['summa']:>14,.0f}")
            print()

        if multi:
            print("=" * 80)
            print(f"BIR NECHTA VARIANT ({len(multi)} ta):")
            for sd, cands in multi:
                print(f"  SD: {sd['name']} (phone {sd['phone']}, bal {sd['summa']:,.0f})")
                for c in cands:
                    print(f"      → DB #{c.id} {c.name} (phone {c.phone}, bal {c.balance:,.0f})")
            print()

        return diffs, multi, not_found
    finally:
        db.close()


def apply_changes(diffs, admin_user_id: int = 1):
    """Tasdiqlanganlardan keyin PartnerBalanceDoc yaratish va balanslarni o'rnatish."""
    if not diffs:
        print("Farq yo'q — hech narsa o'zgartirilmadi.")
        return
    db = SessionLocal()
    try:
        now = datetime.now()
        # Hujjat raqami
        count = db.query(PartnerBalanceDoc).filter(
            PartnerBalanceDoc.date >= now.replace(hour=0, minute=0, second=0, microsecond=0)
        ).count()
        number = f"KNT-{now.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

        doc = PartnerBalanceDoc(
            number=number,
            date=now,
            user_id=admin_user_id,
            status="draft",
        )
        db.add(doc)
        db.flush()

        # Har bir farq uchun PartnerBalanceDocItem qo'shamiz (delta sifatida)
        # Tasdiqlangach partner.balance += delta (mavjud kod shu mantiqda)
        for sd, p, delta in diffs:
            db.add(PartnerBalanceDocItem(
                doc_id=doc.id,
                partner_id=p.id,
                balance=delta,  # delta — tasdiqdan keyin += yoziladi
            ))
        db.commit()
        print(f"✓ Qoralama hujjat yaratildi: {number}")
        print(f"  ID: {doc.id}")
        print(f"  URL: /qoldiqlar/kontragent/hujjat/{doc.id}")
        print()
        print("Hujjat HOLATI: 'draft' (qoralama). Brauzerda ochib KO'RIB CHIQING va")
        print("agar to'g'ri bo'lsa qo'lda 'Tasdiqlash' tugmasini bosing.")
        print()
        print("Tasdiqlash balanslarni avtomatik yangilaydi: partner.balance += delta")
    finally:
        db.close()


if __name__ == "__main__":
    diffs, multi, not_found = report()
    if "--apply" in sys.argv:
        if not diffs:
            print("Farq yo'q.")
            sys.exit(0)
        print("=" * 80)
        ans = input(f"Yuqoridagi {len(diffs)} ta farq uchun QORALAMA hujjat yarataymi? (y/N): ")
        if ans.strip().lower() == "y":
            apply_changes(diffs)
        else:
            print("Bekor qilindi.")
