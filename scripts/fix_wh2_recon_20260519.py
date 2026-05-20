"""WH2 KAROBKA reconcile - INV-20260519-0002 (#101) is_stock_entry bagi tuzatish.

Ildiz-sabab: doc #101 INV-PENDING (QO'SHISH) turi edi, kod
  Stock = old_qty + jismoniy + after_changes
qildi; old_qty = INIT-DRIFT-FIX-W2 sintetik qatorning quantity_after (xom drift).
Natija: 4 ta WH2 KAROBKA noto'g'ri (2 tasi manfiy).

Yechim (Minimal reconcile): har 4 mahsulot uchun Stock = jismoniy son,
ledger SUM = jismoniy bo'lishi uchun BITTA reconcile movement (faqat qo'shuvchi).

ISHLATISH:
  python fix_wh2_recon_20260519.py                 # DRY-RUN (default)
  python fix_wh2_recon_20260519.py --apply         # backup+tranzaksiya+verify

XAVFSIZLIK: DB sentinel ('INV-20260519-0002' doc) tekshiruvidan o'tishi SHART
(soxta/bo'sh faylga yozmaslik). DRY-RUN temp nusxada (jonli DB ga tegmaydi).
--apply avval .bak, BEGIN IMMEDIATE, post-verify fail -> ROLLBACK.
"""
import sys, os, shutil, sqlite3, tempfile, datetime

ARGS = sys.argv[1:]
APPLY = "--apply" in ARGS
DB_ARG = ARGS[ARGS.index("--db") + 1] if "--db" in ARGS else None
CANDIDATES = [c for c in [
    DB_ARG,
    r"\\server2220\d\TOTLI BI\totli_holva.db",
    r"D:\TOTLI BI\totli_holva.db",
] if c]

WH = 2
SENTINEL_DOC = "INV-20260519-0002"
TARGETS = [  # (product_id, code, jismoniy_son) - doc #101, foydalanuvchi tasdiqlagan
    (116, "P167", 1800.0),
    (122, "P185", 1300.0),
    (115, "P166", 2000.0),
    (62,  "P108", 1900.0),
]
EPS = 1e-6


def snapshot(path):
    """Jonli DB ni temp ga nusxalab (proven pattern), sentinel tekshirib temp yo'lini qaytaradi."""
    tmp = os.path.join(tempfile.gettempdir(),
                       f"wh2recon_chk_{datetime.datetime.now():%Y%m%d_%H%M%S_%f}.db")
    shutil.copy2(path, tmp)
    con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"stocks", "stock_movements", "stock_adjustment_docs"} <= names:
            return None, tmp
        row = con.execute("SELECT id FROM stock_adjustment_docs WHERE number=?",
                          (SENTINEL_DOC,)).fetchone()
        return (row[0] if row else None), tmp
    finally:
        con.close()


def resolve():
    for p in CANDIDATES:
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            continue
        try:
            doc_id, tmp = snapshot(p)
        except Exception as e:
            print(f"  {p}: snapshot xato {e}")
            continue
        if doc_id:
            return p, doc_id, tmp
        os.remove(tmp)
    return None, None, None


def compute_plan(cur):
    plan = []
    for pid, code, phys in TARGETS:
        srow = cur.execute(
            "SELECT id, quantity FROM stocks WHERE warehouse_id=? AND product_id=?",
            (WH, pid)).fetchall()
        if len(srow) != 1:
            raise RuntimeError(f"P{code}(id={pid}): {len(srow)} ta Stock row (1 kutilgan)")
        cur_stock = float(srow[0][1] or 0)
        led = float(cur.execute(
            "SELECT COALESCE(SUM(quantity_change),0) FROM stock_movements "
            "WHERE warehouse_id=? AND product_id=?", (WH, pid)).fetchone()[0])
        plan.append(dict(pid=pid, code=code, phys=phys, stock_id=srow[0][0],
                         cur_stock=cur_stock, led=led, delta=phys - led))
    return plan


def main():
    DB, doc_id, tmp = resolve()
    if not DB:
        print(f"XATO: jonli DB tasdiqlanmadi (sentinel '{SENTINEL_DOC}'). "
              f"Tekshirilgan: {CANDIDATES}")
        sys.exit(1)
    print(f"DB: {DB}  (sentinel doc#{doc_id} OK)")
    print(f"Rejim: {'APPLY (yoziladi)' if APPLY else 'DRY-RUN (jonli DB ga tegmaydi)'}")
    print("=" * 70)

    if not APPLY:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        for p in compute_plan(con.cursor()):
            print(f"P{p['code']} (id={p['pid']}): Stock {p['cur_stock']:+.2f} -> "
                  f"{p['phys']:.2f} | LedgerSUM {p['led']:+.2f} -> {p['phys']:.2f} "
                  f"| reconcile mv={p['delta']:+.2f}")
        con.close()
        os.remove(tmp)
        print("=" * 70)
        print("DRY-RUN tugadi. Yozish:  python fix_wh2_recon_20260519.py --apply")
        return

    os.remove(tmp)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{DB}.pre-wh2recon.{ts}.bak"
    shutil.copy2(DB, bak)
    print(f"Backup OK: {bak} ({os.path.getsize(bak)/1e6:.1f} MB)\n")

    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    c = con.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        c.execute("BEGIN IMMEDIATE")
        # sentinel re-check jonli ulanishda
        if not c.execute("SELECT 1 FROM stock_adjustment_docs WHERE number=?",
                         (SENTINEL_DOC,)).fetchone():
            raise RuntimeError("sentinel jonli ulanishda yo'q - TO'XTASH")
        plan = compute_plan(c)
        for p in plan:
            print(f"P{p['code']}: Stock {p['cur_stock']:+.2f}->{p['phys']:.2f} "
                  f"Ledger {p['led']:+.2f}->{p['phys']:.2f} mv={p['delta']:+.2f}")
            if abs(p["delta"]) > EPS:
                c.execute(
                    "INSERT INTO stock_movements "
                    "(stock_id,warehouse_id,product_id,operation_type,document_type,"
                    " document_id,document_number,quantity_change,quantity_after,"
                    " note,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (p["stock_id"], WH, p["pid"], "adjustment", "StockReconcile",
                     0, f"INV-RECON-W2-{p['code']}-20260519",
                     p["delta"], p["phys"],
                     "WH2 KAROBKA reconcile: INV-20260519-0002 is_stock_entry "
                     "bagi; jismoniy sanoq = haqiqat", now))
            c.execute("UPDATE stocks SET quantity=?, updated_at=? WHERE id=?",
                      (p["phys"], now, p["stock_id"]))
        ok = True
        for p in plan:
            s = float(c.execute("SELECT quantity FROM stocks WHERE id=?",
                                (p["stock_id"],)).fetchone()[0])
            l = float(c.execute(
                "SELECT COALESCE(SUM(quantity_change),0) FROM stock_movements "
                "WHERE warehouse_id=? AND product_id=?",
                (WH, p["pid"])).fetchone()[0])
            good = abs(s - p["phys"]) < 1e-3 and abs(l - p["phys"]) < 1e-3
            ok = ok and good
            print(f"VERIFY P{p['code']}: Stock={s:.2f} LedgerSUM={l:.2f} "
                  f"target={p['phys']:.2f} {'OK' if good else 'XATO'}")
        if not ok:
            con.rollback()
            print("\n!!! VERIFY FAIL -> ROLLBACK. O'zgarmadi.")
            sys.exit(3)
        con.commit()
        print("\nCOMMIT OK. 4 ta WH2 KAROBKA reconcile qilindi.")
    except Exception as e:
        con.rollback()
        print(f"\n!!! XATO -> ROLLBACK: {type(e).__name__}: {e}")
        sys.exit(4)
    finally:
        con.close()


if __name__ == "__main__":
    main()
