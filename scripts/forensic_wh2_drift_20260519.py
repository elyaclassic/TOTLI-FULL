"""WH2 drift forensikasi — READ-ONLY. Jonli DB nusxasini olib tahlil qiladi.
Hech qanday yozuv YO'Q. Phase 1 (systematic-debugging) dalil yig'ish.
"""
import os, shutil, sqlite3, tempfile, datetime, sys

LIVE = r"\\server2220\d\TOTLI BI\totli_holva.db"
tmp = os.path.join(tempfile.gettempdir(), f"totli_forensic_{datetime.datetime.now():%Y%m%d_%H%M%S}.db")
print(f"Copy live -> {tmp}")
shutil.copy2(LIVE, tmp)
con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
c = con.cursor()

def q(sql, p=()):
    return c.execute(sql, p).fetchall()

print("\n=== WAREHOUSES ===")
for r in q("SELECT id,code,name FROM warehouses ORDER BY id"):
    print(dict(r))

print("\n=== PRODUCT P167 / id=116 / id=122 ===")
for r in q("SELECT id,code,name,unit_id FROM products WHERE code='P167' OR id IN (116,122)"):
    print(dict(r))

print("\n=== INV-20260519-0002 DOC ===")
docs = q("SELECT id,number,status,warehouse_id,date,total_tannarx FROM stock_adjustment_docs WHERE number LIKE 'INV-20260519-0002%' OR number LIKE '%20260519%'")
for r in docs:
    print(dict(r))

# Bugungi barcha INV/PENDING hujjatlar
print("\n=== BUGUN (2026-05-19) tasdiqlangan adjustment docs ===")
for r in q("SELECT id,number,status,warehouse_id,date FROM stock_adjustment_docs WHERE date>='2026-05-19 00:00:00' ORDER BY id"):
    print(dict(r))

target_doc = None
for r in docs:
    if (r["number"] or "").startswith("INV-20260519-0002"):
        target_doc = dict(r)
if not target_doc and docs:
    target_doc = dict(docs[0])
print(f"\n>>> TARGET DOC = {target_doc}")

if target_doc:
    did = target_doc["id"]
    ddate = target_doc["date"]
    print(f"\n=== DOC #{did} ITEMS (date={ddate}) ===")
    items = q("SELECT id,warehouse_id,product_id,quantity,previous_quantity,cost_price FROM stock_adjustment_doc_items WHERE doc_id=?", (did,))
    for r in items:
        print(dict(r))

    print(f"\n=== HAR ITEM PAIR uchun chuqur tahlil ===")
    for it in items:
        wh, pid = it["warehouse_id"], it["product_id"]
        pname = q("SELECT code,name FROM products WHERE id=?", (pid,))
        pn = dict(pname[0]) if pname else {}
        print(f"\n--- WH={wh} PROD={pid} ({pn.get('code')} {pn.get('name')}) phys={it['quantity']} ---")
        srows = q("SELECT id,quantity,updated_at FROM stocks WHERE warehouse_id=? AND product_id=?", (wh, pid))
        print(f"  Stock rows (count={len(srows)}): {[dict(s) for s in srows]}")
        led = q("SELECT COALESCE(SUM(quantity_change),0) s, COUNT(*) n FROM stock_movements WHERE warehouse_id=? AND product_id=?", (wh, pid))
        print(f"  Ledger SUM={led[0]['s']} (n={led[0]['n']})")
        ac = q("""SELECT COALESCE(SUM(quantity_change),0) s, COUNT(*) n FROM stock_movements
                  WHERE warehouse_id=? AND product_id=? AND created_at>? AND operation_type!='adjustment'""", (wh, pid, ddate))
        print(f"  after_changes (created_at>{ddate}, op!=adjustment) = {ac[0]['s']} (n={ac[0]['n']})")
        print(f"  >>> FORMULA new_qty + after_changes = {float(it['quantity']) + float(ac[0]['s'])}")
        # after_changes tarkibi (top 20 by abs)
        comp = q("""SELECT id,created_at,operation_type,document_type,document_number,quantity_change,quantity_after
                    FROM stock_movements WHERE warehouse_id=? AND product_id=? AND created_at>? AND operation_type!='adjustment'
                    ORDER BY ABS(quantity_change) DESC LIMIT 15""", (wh, pid, ddate))
        print("  after_changes TOP komponentlar:")
        for r in comp:
            print(f"    {dict(r)}")
        # dublikat movement (bir xil doc_number+qty+op, >1)
        dup = q("""SELECT document_type,document_number,operation_type,quantity_change,COUNT(*) n
                   FROM stock_movements WHERE warehouse_id=? AND product_id=?
                   GROUP BY document_type,document_number,operation_type,quantity_change HAVING n>1 ORDER BY n DESC""", (wh, pid))
        if dup:
            print("  !!! DUBLIKAT movement guruhlari:")
            for r in dup:
                print(f"    {dict(r)}")
        # to'liq ledger (oxirgi 40)
        full = q("""SELECT id,created_at,operation_type,document_type,document_number,quantity_change,quantity_after
                    FROM stock_movements WHERE warehouse_id=? AND product_id=? ORDER BY id DESC LIMIT 40""", (wh, pid))
        print("  TO'LIQ ledger (oxirgi 40, id DESC):")
        for r in full:
            print(f"    {dict(r)}")

print("\n=== WH2 (barcha) duplicate Stock rows ===")
# WH2 ni nomi bilan aniqlash
wh2 = q("SELECT id FROM warehouses WHERE name LIKE '%Yarim tayyor%' OR name LIKE '%yarim%'")
wh2ids = [r["id"] for r in wh2]
print(f"WH2 candidate ids by name: {wh2ids}")
for r in q("""SELECT warehouse_id,product_id,COUNT(*) n FROM stocks
              GROUP BY warehouse_id,product_id HAVING n>1 ORDER BY n DESC LIMIT 30"""):
    print(f"  DUP STOCK ROW: {dict(r)}")

print("\n=== INIT-* dublikat movementlar (global, WH2 product) ===")
for r in q("""SELECT document_number,operation_type,COUNT(*) n, SUM(quantity_change) s
              FROM stock_movements WHERE document_number LIKE 'INIT%'
              GROUP BY document_number,operation_type HAVING n>1 ORDER BY n DESC LIMIT 30"""):
    print(f"  {dict(r)}")

con.close()
os.remove(tmp)
print(f"\nDONE. Temp removed.")
