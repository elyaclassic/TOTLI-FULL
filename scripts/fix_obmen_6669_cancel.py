"""Obmen 6669 (AGT-20260518-009) bekor + juft 6670 uzish.

Sabab: 6669 return_sale/confirmed obmen, joriy kodda confirmed AGT
obmen'ni to'g'ri bekor qiladigan endpoint yo'q. Bu obmen side-effectsiz
(stock yo'q, payment yo'q, debt=0, prev_balance NULL) -> xavfsiz
qo'lda tuzatish:
  - 6669: status confirmed -> cancelled
  - 6670 (child, draft sale): parent_order_id -> NULL (mustaqil draft)

XAVFSIZLIK GUARD: agar 6669'da stock_movement/payment bo'lsa yoki
debt!=0 yoki type!=return_sale -> RAD etadi (side-effect bor demak,
qo'lда tergov kerak).

Idempotent: 6669 allaqachon cancelled bo'lsa -> ALREADY_DONE.
Default DRY-RUN. --apply bilan qo'llang. Backup avtomatik (DB nusxa).

Ishlatish (D:\\TOTLI BI dan):
    python scripts/fix_obmen_6669_cancel.py [--apply]
"""
import sys
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "totli_holva.db"
RETURN_ID = 6669
CHILD_ID = 6670


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    if not DB.exists():
        print(f"XATO: DB topilmadi: {DB}")
        sys.exit(1)

    if apply:
        bak = DB.with_suffix(
            f".db.pre-obmen6669.{datetime.now():%Y%m%d_%H%M%S}.bak"
        )
        shutil.copy2(DB, bak)
        print(f"Backup: {bak.name}")

    con = sqlite3.connect(DB)
    cur = con.cursor()

    r = cur.execute(
        "SELECT id,number,type,status,debt,paid,previous_partner_balance "
        "FROM orders WHERE id=?", (RETURN_ID,)
    ).fetchone()
    if not r:
        print(f"XATO: order {RETURN_ID} topilmadi")
        sys.exit(1)
    oid, num, otype, status, debt, paid, prevbal = r
    print(f"6669: {num} type={otype} status={status} debt={debt} "
          f"paid={paid} prev_balance={prevbal}")

    if status == "cancelled":
        print("ALREADY_DONE: 6669 allaqachon cancelled. Hech narsa qilinmadi.")
        con.close()
        return

    # --- XAVFSIZLIK GUARD ---
    problems = []
    if otype != "return_sale":
        problems.append(f"type={otype} (return_sale kutilgan)")
    if status != "confirmed":
        problems.append(f"status={status} (confirmed kutilgan)")
    if (debt or 0) != 0:
        problems.append(f"debt={debt} (0 kutilgan)")
    if (paid or 0) != 0:
        problems.append(f"paid={paid} (0 kutilgan)")
    sm = cur.execute(
        "SELECT COUNT(*) FROM stock_movements WHERE document_id=? OR "
        "document_number=(SELECT number FROM orders WHERE id=?)",
        (RETURN_ID, RETURN_ID)
    ).fetchone()[0]
    if sm:
        problems.append(f"stock_movements={sm} (0 kutilgan - side-effect bor!)")
    pay = cur.execute(
        "SELECT COUNT(*) FROM payments WHERE description LIKE ?",
        (f"%{num}%",)
    ).fetchone()[0]
    if pay:
        problems.append(f"payments={pay} (0 kutilgan - side-effect bor!)")
    if problems:
        print("RAD ETILDI - side-effect bor, qo'lда tergov kerak:")
        for p in problems:
            print("  - " + p)
        con.close()
        sys.exit(1)

    ch = cur.execute(
        "SELECT id,number,type,status,parent_order_id FROM orders WHERE id=?",
        (CHILD_ID,)
    ).fetchone()
    print(f"6670: {ch[1] if ch else '—'} type={ch[2] if ch else '—'} "
          f"status={ch[3] if ch else '—'} parent={ch[4] if ch else '—'}")
    if not ch or ch[4] != RETURN_ID:
        print(f"DIQQAT: 6670 6669 ning child emas (parent="
              f"{ch[4] if ch else None}). Faqat 6669 bekor qilinadi.")

    print()
    print("REJA:")
    print(f"  6669 status: confirmed -> cancelled")
    if ch and ch[4] == RETURN_ID:
        print(f"  6670 parent_order_id: {RETURN_ID} -> NULL "
              f"(mustaqil draft sale qoladi)")

    if not apply:
        print("\nDRY-RUN - hech narsa yozilmadi. --apply bilan qo'llang.")
        con.close()
        return

    cur.execute("UPDATE orders SET status='cancelled' WHERE id=? "
                "AND status='confirmed'", (RETURN_ID,))
    n1 = cur.rowcount
    n2 = 0
    if ch and ch[4] == RETURN_ID:
        cur.execute("UPDATE orders SET parent_order_id=NULL WHERE id=? "
                    "AND parent_order_id=?", (CHILD_ID, RETURN_ID))
        n2 = cur.rowcount
    con.commit()

    v6669 = cur.execute("SELECT status FROM orders WHERE id=?",
                         (RETURN_ID,)).fetchone()[0]
    v6670 = cur.execute("SELECT parent_order_id FROM orders WHERE id=?",
                        (CHILD_ID,)).fetchone()
    print(f"\nQO'LLANDI: 6669 status={v6669} (UPDATE {n1}), "
          f"6670 parent={v6670[0] if v6670 else '—'} (UPDATE {n2})")
    print("OK" if v6669 == "cancelled" else "TEKSHIR: 6669 cancelled emas")
    con.close()


if __name__ == "__main__":
    main()
