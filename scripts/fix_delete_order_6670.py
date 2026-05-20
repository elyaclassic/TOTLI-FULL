"""Order 6670 (AGT-20260518-010) — hard delete (obmen jufti).

Foydalanuvchi: obmen 6669 bekor qilindi, 6670 (draft sale legi) ham
o'chirilsin, yangidan kiritiladi.

XAVFSIZLIK GUARD: faqat status='draft' AND type='sale' AND
parent_order_id IS NULL AND stock_movements=0 AND payments=0 bo'lsa
o'chiradi. Aks holda RAD (side-effect bor -> hard delete TAQIQ).
order_items avval o'chiriladi (FK).

Idempotent: 6670 yo'q bo'lsa -> ALREADY_DONE.
Default DRY-RUN. --apply bilan. Backup avtomatik (DB nusxa).

Ishlatish (D:\\TOTLI BI dan):
    python scripts/fix_delete_order_6670.py [--apply]
"""
import sys
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "totli_holva.db"
OID = 6670


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    if not DB.exists():
        print(f"XATO: DB topilmadi: {DB}")
        sys.exit(1)

    con = sqlite3.connect(DB)
    cur = con.cursor()

    r = cur.execute(
        "SELECT id,number,type,status,parent_order_id,debt,paid "
        "FROM orders WHERE id=?", (OID,)
    ).fetchone()
    if not r:
        print(f"ALREADY_DONE: order {OID} topilmadi (allaqachon o'chirilgan).")
        con.close()
        return
    oid, num, otype, status, parent, debt, paid = r
    print(f"6670: {num} type={otype} status={status} parent={parent} "
          f"debt={debt} paid={paid}")

    # --- XAVFSIZLIK GUARD ---
    problems = []
    if otype != "sale":
        problems.append(f"type={otype} (sale kutilgan)")
    if status != "draft":
        problems.append(f"status={status} (draft kutilgan - confirmed/"
                         f"completed order hard delete TAQIQ)")
    if parent is not None:
        problems.append(f"parent_order_id={parent} (NULL kutilgan)")
    if (paid or 0) != 0:
        problems.append(f"paid={paid} (0 kutilgan)")
    sm = cur.execute(
        "SELECT COUNT(*) FROM stock_movements WHERE document_id=? OR "
        "document_number=?", (OID, num)
    ).fetchone()[0]
    if sm:
        problems.append(f"stock_movements={sm} (0 kutilgan - side-effect!)")
    pay = cur.execute(
        "SELECT COUNT(*) FROM payments WHERE description LIKE ?",
        (f"%{num}%",)
    ).fetchone()[0]
    if pay:
        problems.append(f"payments={pay} (0 kutilgan - side-effect!)")
    if problems:
        print("RAD ETILDI - hard delete xavfsiz emas:")
        for p in problems:
            print("  - " + p)
        con.close()
        sys.exit(1)

    n_items = cur.execute(
        "SELECT COUNT(*) FROM order_items WHERE order_id=?", (OID,)
    ).fetchone()[0]
    print(f"order_items: {n_items} ta (avval o'chiriladi - FK)")
    print()
    print("REJA: order_items o'chir -> orders qatori 6670 o'chir (HARD DELETE, qaytmas)")

    if not apply:
        print("\nDRY-RUN - hech narsa yozilmadi. --apply bilan qo'llang.")
        con.close()
        return

    bak = DB.parent / (
        DB.name + f".pre-del6670.{datetime.now():%Y%m%d_%H%M%S}.bak"
    )
    shutil.copy2(DB, bak)
    print(f"Backup: {bak.name}")

    cur.execute("DELETE FROM order_items WHERE order_id=?", (OID,))
    di = cur.rowcount
    cur.execute("DELETE FROM orders WHERE id=? AND status='draft' "
                "AND type='sale'", (OID,))
    do = cur.rowcount
    con.commit()

    gone = cur.execute("SELECT COUNT(*) FROM orders WHERE id=?",
                        (OID,)).fetchone()[0]
    print(f"\nQO'LLANDI: order_items DELETE {di}, orders DELETE {do}")
    print("OK - 6670 o'chirildi" if gone == 0
          else "TEKSHIR: 6670 hali bor")
    con.close()


if __name__ == "__main__":
    main()
