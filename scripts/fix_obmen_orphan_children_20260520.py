"""Obmen child auto-confirm regressiyasi (b881e3c) — 2 ta orphan child fix.

Ildiz: b881e3c (2026-05-18) supervisor_confirm_agent_order'dan
return_sale child auto-confirm blokini olib tashlagan (early return va
apply_return_stock_addition bilan birga). Lekin agents/detail.html dispatch
tugmasi ex_child.status=='confirmed' shartiga bog'liq -> child draft'da
qolib, dispatch yashirin, haydovchi tayinlanmaydi.

Bu skript 2 ta orphan child (6666, 6781) ni atomik tarzda confirmed'ga
o'tkazadi. Idempotent (status='draft' guard). Sentinel.

ISHLATISH:
  python fix_obmen_orphan_children_20260520.py             # DRY-RUN
  python fix_obmen_orphan_children_20260520.py --apply     # atomik UPDATE
"""
import sys, os, sqlite3, datetime

ARGS = sys.argv[1:]
APPLY = "--apply" in ARGS
CANDIDATES = [
    r"\\server2220\d\TOTLI BI\totli_holva.db",
    r"D:\TOTLI BI\totli_holva.db",
]
TARGETS = [
    # (child_id, child_num, parent_id, parent_num)
    (6666, "AGT-20260518-006", 6665, "AGT-20260518-005"),
    (6781, "AGT-20260519-012", 6780, "AGT-20260519-011"),
]


def find_db():
    for p in CANDIDATES:
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            continue
        try:
            con = sqlite3.connect(p)
            # Sentinel: orders + 2 ta target child mavjudligi
            row = con.execute(
                "SELECT COUNT(*) FROM orders WHERE id IN (6666, 6781) AND type='sale'"
            ).fetchone()
            con.close()
            if row[0] == 2:
                return p
        except Exception:
            pass
    return None


def main():
    db = find_db()
    if not db:
        print("XATO: jonli DB tasdiqlanmadi (target orderlar topilmadi).")
        sys.exit(1)
    print(f"DB: {db}")
    print(f"Rejim: {'APPLY' if APPLY else 'DRY-RUN'}")
    print("=" * 70)

    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    c = con.cursor()

    plan = []
    for child_id, child_num, parent_id, parent_num in TARGETS:
        r = c.execute(
            "SELECT id, status, type, parent_order_id, user_id FROM orders WHERE id=?",
            (child_id,)
        ).fetchone()
        if not r:
            print(f"  !!! {child_num} (id={child_id}) topilmadi")
            continue
        cid, status, ctype, pid, uid = r
        parent_uid = c.execute(
            "SELECT user_id FROM orders WHERE id=?", (parent_id,)
        ).fetchone()[0]
        if status != "draft" or ctype != "sale" or pid != parent_id:
            print(f"  SKIP {child_num}: status={status} type={ctype} parent={pid} (kutilgan: draft/sale/{parent_id})")
            continue
        new_uid = uid if uid is not None else parent_uid
        plan.append((child_id, child_num, new_uid))
        print(f"  {child_num} (id={child_id}): status draft->confirmed | user_id {uid}->{new_uid} (parent {parent_num} uid={parent_uid})")

    print("=" * 70)
    if not APPLY:
        print("DRY-RUN tugadi. Yozish:  python fix_obmen_orphan_children_20260520.py --apply")
        con.close()
        return

    try:
        c.execute("BEGIN IMMEDIATE")
        for child_id, child_num, new_uid in plan:
            r = c.execute(
                "UPDATE orders SET status='confirmed', user_id=? "
                "WHERE id=? AND status='draft' AND type='sale'",
                (new_uid, child_id)
            )
            if r.rowcount != 1:
                raise RuntimeError(f"{child_num} update failed (rowcount={r.rowcount})")
            print(f"  UPDATED {child_num}")
        # Verify
        for child_id, child_num, _ in plan:
            s = c.execute("SELECT status FROM orders WHERE id=?", (child_id,)).fetchone()[0]
            if s != "confirmed":
                raise RuntimeError(f"{child_num} verify failed: status={s}")
        con.commit()
        print(f"\nCOMMIT OK. {len(plan)} ta orphan child confirmed.")
    except Exception as e:
        con.rollback()
        print(f"\n!!! XATO -> ROLLBACK: {type(e).__name__}: {e}")
        sys.exit(4)
    finally:
        con.close()


if __name__ == "__main__":
    main()
