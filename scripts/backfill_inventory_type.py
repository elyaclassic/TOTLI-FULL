"""Eski StockAdjustmentDoc hujjatlariga 'type' qiymatini backfill qiladi.

Manba: stock_movements.note (haqiqiy bajarilgan semantika), CHUNKI doc.number
confirm'da qayta nomlanadi (INV-PENDING -> INV-YYYYMMDD).

ISHLATISH:
  python backfill_inventory_type.py             # DRY-RUN (default)
  python backfill_inventory_type.py --apply     # backup + bitta tranzaksiya
"""
import sys, os, shutil, sqlite3, datetime

ARGS = sys.argv[1:]
APPLY = "--apply" in ARGS
CANDIDATES = [
    r"\\server2220\d\TOTLI BI\totli_holva.db",
    r"D:\TOTLI BI\totli_holva.db",
]
# Sentinel: ustun mavjudligini tasdiqlash
SENTINEL_TABLE = "stock_adjustment_docs"
SENTINEL_COL = "type"


def find_db():
    for p in CANDIDATES:
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            continue
        try:
            con = sqlite3.connect(p)
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({SENTINEL_TABLE})")}
            con.close()
            if SENTINEL_COL in cols:
                return p
        except Exception:
            pass
    return None


def classify(notes, number):
    notes = [n or "" for n in notes]
    if any(n.startswith(("Tovar qoldiqlari", "Qoldiq kiritish")) for n in notes):
        return "stock_entry"
    if any(n.startswith("Inventarizatsiya") for n in notes):
        return "inventory"
    if (number or "").startswith("QLD"):
        return "stock_entry"
    return "inventory"


def main():
    db = find_db()
    if not db:
        print(f"XATO: jonli DB topilmadi yoki '{SENTINEL_COL}' ustuni hali qo'shilmagan.")
        sys.exit(1)
    print(f"DB: {db}")
    print(f"Rejim: {'APPLY' if APPLY else 'DRY-RUN'}")
    print("=" * 70)

    if APPLY:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = f"{db}.pre-typebackfill.{ts}.bak"
        shutil.copy2(db, bak)
        print(f"Backup: {bak}")

    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    c = con.cursor()
    docs = c.execute(
        "SELECT id, number, COALESCE(type,'') FROM stock_adjustment_docs ORDER BY id"
    ).fetchall()
    plan = {"inventory": 0, "stock_entry": 0, "unchanged": 0}
    samples = []
    updates = []
    for doc_id, number, cur_type in docs:
        notes = [r[0] for r in c.execute(
            "SELECT note FROM stock_movements WHERE document_type='StockAdjustmentDoc' AND document_id=?",
            (doc_id,)
        ).fetchall()]
        new_type = classify(notes, number)
        if cur_type == new_type:
            plan["unchanged"] += 1
            continue
        plan[new_type] += 1
        updates.append((new_type, doc_id))
        if len(samples) < 10:
            samples.append((doc_id, number, cur_type, new_type))
    print(f"Jami: {len(docs)} | yangilanadi inventory: {plan['inventory']} | "
          f"stock_entry: {plan['stock_entry']} | o'zgarmaydi: {plan['unchanged']}")
    print("Namuna 10 ta:")
    for s in samples:
        print(f"  doc#{s[0]} number={s[1]!r} {s[2]!r} -> {s[3]!r}")
    if not APPLY:
        print("=" * 70)
        print("DRY-RUN tugadi. Yozish:  python backfill_inventory_type.py --apply")
        con.close()
        return
    try:
        c.execute("BEGIN IMMEDIATE")
        for new_type, doc_id in updates:
            c.execute(
                "UPDATE stock_adjustment_docs SET type=? WHERE id=?",
                (new_type, doc_id),
            )
        con.commit()
        print(f"COMMIT OK. {len(updates)} hujjat yangilandi.")
    except Exception as e:
        con.rollback()
        print(f"!!! XATO -> ROLLBACK: {type(e).__name__}: {e}")
        sys.exit(4)
    finally:
        con.close()


if __name__ == "__main__":
    main()
