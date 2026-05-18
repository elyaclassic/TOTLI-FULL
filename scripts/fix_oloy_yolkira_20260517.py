"""
OLOY GUZAR SERVIS — yo'l kira (P-20260517-0015) tuzatish.

MUAMMO: Xarid hujjatining "Xarajat" qatori (yo'l kiro 600,000) confirm paytida
OLOY qarziga qo'shilgan (partner.balance -= mahsulot + xarajat). Lekin yo'l kira
haydovchiga ALOHIDA naqd to'langan, OLOYga emas. Natija:
  - OLOY balansi −600,000 (noto'g'ri; mahsulot 9.2M allaqachon to'langan)
  - Haydovchiga to'langan 600,000 hech qayerda yozilmagan (Asosiy kassa naqd oshirib ko'rsatilgan)
  - Mahsulot tan narxida 600,000 BOR — bu TO'G'RI (landed cost), TEGILMAYDI.

TUZATISH (2 yozuv, tan narxga tegmasdan):
  1) Kontragent balans hujjati (KNT-): OLOY +600,000 → balans −600,000 dan 0 ga
     (qoldiqlar.py:590-591 mantig'i: partner.balance += item.balance, previous_balance snapshot)
  2) Payment (expense, naqd, Asosiy kassa id=1) 600,000 — haydovchiga real chiqim
     (cash_balance_formula confirmed expense'ni hisobga oladi → kassa real kamayadi)

Idempotent: DRVFIX-P-20260517-0015 markeri bo'lsa qayta bajarmaydi.
Ishlatish:
  python scripts/fix_oloy_yolkira_20260517.py "D:\\TOTLI BI\\totli_holva.db"          # DRY-RUN
  python scripts/fix_oloy_yolkira_20260517.py "D:\\TOTLI BI\\totli_holva.db" --apply   # qo'llash
"""
import sys
import sqlite3
from datetime import datetime

PARTNER_ID = 719          # OLOY GUZAR SERVIS
CASH_REGISTER_ID = 1      # Asosiy kassa (naqd)
AMOUNT = 600000.0
MARKER = "DRVFIX-P-20260517-0015"
DESC = (f"{MARKER}: yo'l kira haydovchiga naqd to'landi; "
        f"OLOY qarziga xato qo'shilgani uchun korreksiya (xarid P-20260517-0015)")


def main():
    if len(sys.argv) < 2:
        print("Foydalanish: python fix_oloy_yolkira_20260517.py <db_path> [--apply]")
        sys.exit(1)
    db_path = sys.argv[1]
    apply = "--apply" in sys.argv

    con = sqlite3.connect(db_path)
    c = con.cursor()

    # Idempotent guard
    c.execute("SELECT COUNT(*) FROM payments WHERE description LIKE ?", (f"%{MARKER}%",))
    if c.fetchone()[0] > 0:
        print(f"[SKIP] '{MARKER}' allaqachon qo'llangan. Hech narsa qilinmadi.")
        con.close()
        return

    c.execute("SELECT name, balance FROM partners WHERE id=?", (PARTNER_ID,))
    row = c.fetchone()
    if not row:
        print(f"[XATO] Partner {PARTNER_ID} topilmadi.")
        con.close()
        sys.exit(1)
    pname, pbal = row[0], float(row[1] or 0)
    c.execute("SELECT name FROM cash_registers WHERE id=?", (CASH_REGISTER_ID,))
    kassa = (c.fetchone() or ["?"])[0]

    new_bal = pbal + AMOUNT
    print("=" * 60)
    print(f"  Partner: {pname} (#{PARTNER_ID})")
    print(f"  OLOY balansi: {pbal:,.0f}  ->  {new_bal:,.0f}  (+{AMOUNT:,.0f})")
    print(f"  Yangi Payment: CHIQIM {AMOUNT:,.0f} naqd, kassa='{kassa}' (#{CASH_REGISTER_ID})")
    print(f"  Izoh: {DESC}")
    print("=" * 60)

    if not apply:
        print("DRY-RUN — hech narsa o'zgartirilmadi. Qo'llash uchun: --apply")
        con.close()
        return

    now = datetime.now()
    day = now.strftime("%Y%m%d")

    # --- 1) Kontragent balans hujjati (KNT-) ---
    c.execute(
        "SELECT COUNT(*) FROM partner_balance_docs WHERE date>=? AND date<?",
        (now.strftime("%Y-%m-%d 00:00:00"), now.strftime("%Y-%m-%d 23:59:59")),
    )
    knt_seq = c.fetchone()[0] + 1
    knt_number = f"KNT-{day}-{str(knt_seq).zfill(4)}"
    c.execute(
        "INSERT INTO partner_balance_docs (number, date, user_id, status, created_at) "
        "VALUES (?, ?, NULL, 'confirmed', ?)",
        (knt_number, now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    doc_id = c.lastrowid
    c.execute(
        "INSERT INTO partner_balance_doc_items (doc_id, partner_id, balance, previous_balance) "
        "VALUES (?, ?, ?, ?)",
        (doc_id, PARTNER_ID, AMOUNT, pbal),
    )
    c.execute("UPDATE partners SET balance=? WHERE id=?", (new_bal, PARTNER_ID))

    # --- 2) Payment (expense, naqd) — haydovchiga real chiqim ---
    c.execute(
        "SELECT number FROM payments WHERE number LIKE ? ORDER BY id DESC LIMIT 1",
        (f"PAY-{day}-%",),
    )
    last = c.fetchone()
    if last and last[0]:
        try:
            pay_seq = int(last[0].split("-")[-1]) + 1
        except (ValueError, IndexError):
            pay_seq = 1
    else:
        pay_seq = 1
    pay_number = f"PAY-{day}-{str(pay_seq).zfill(4)}"
    c.execute(
        "INSERT INTO payments (number, date, type, cash_register_id, partner_id, order_id, "
        "amount, payment_type, category, description, user_id, created_at, status) "
        "VALUES (?, ?, 'expense', ?, NULL, NULL, ?, 'cash', 'other', ?, NULL, ?, 'confirmed')",
        (pay_number, now.strftime("%Y-%m-%d %H:%M:%S"), CASH_REGISTER_ID, AMOUNT, DESC,
         now.strftime("%Y-%m-%d %H:%M:%S")),
    )

    con.commit()

    c.execute("SELECT balance FROM partners WHERE id=?", (PARTNER_ID,))
    after = float(c.fetchone()[0] or 0)
    print(f"[OK] Qo'llandi.")
    print(f"  Balans hujjati: {knt_number} (doc_id={doc_id})")
    print(f"  Chiqim: {pay_number} — {AMOUNT:,.0f} naqd, kassa #{CASH_REGISTER_ID}")
    print(f"  OLOY balansi endi: {after:,.0f}")
    con.close()


if __name__ == "__main__":
    main()
