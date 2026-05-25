"""WH2 drift — MIQYOS aniqlash. READ-ONLY. Phase 1 davomi."""
import os, shutil, sqlite3, tempfile, datetime
LIVE = r"\\server2220\d\TOTLI BI\totli_holva.db"
tmp = os.path.join(tempfile.gettempdir(), f"totli_scope_{datetime.datetime.now():%Y%m%d_%H%M%S}.db")
shutil.copy2(LIVE, tmp)
con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True); con.row_factory = sqlite3.Row
c = con.cursor()
def q(s, p=()): return c.execute(s, p).fetchall()

print("=== DOC #100 (INV-20260519-0001) ITEMS + natija ===")
for it in q("SELECT id,warehouse_id,product_id,quantity,previous_quantity FROM stock_adjustment_doc_items WHERE doc_id=100"):
    d = dict(it); wh, pid = d['warehouse_id'], d['product_id']
    st = q("SELECT quantity FROM stocks WHERE warehouse_id=? AND product_id=?", (wh, pid))
    mv = q("""SELECT quantity_change,operation_type FROM stock_movements
              WHERE document_number='INV-20260519-0001' AND product_id=? AND warehouse_id=?""", (pid, wh))
    pn = q("SELECT code,name FROM products WHERE id=?", (pid,))
    print(f"  {dict(pn[0]) if pn else pid} phys={d['quantity']} prev={d['previous_quantity']} -> Stock={st[0]['quantity'] if st else None} mv={[dict(m) for m in mv]}")

print("\n=== BARCHA manfiy Stock (qiymat<0) ===")
for r in q("""SELECT s.warehouse_id, w.name wname, s.product_id, p.code, p.name, s.quantity
              FROM stocks s JOIN warehouses w ON w.id=s.warehouse_id JOIN products p ON p.id=s.product_id
              WHERE s.quantity < -0.001 ORDER BY s.quantity"""):
    print(f"  {dict(r)}")

print("\n=== INV-PENDING / tovar-qoldiqlari hujjatlar (is_stock_entry yo'li) ===")
for r in q("""SELECT id,number,status,warehouse_id,date FROM stock_adjustment_docs
              WHERE number LIKE 'INV-PENDING%' OR id IN (
                SELECT DISTINCT document_id FROM stock_movements
                WHERE note LIKE 'Tovar qoldiqlari%') ORDER BY id DESC LIMIT 20"""):
    print(f"  {dict(r)}")

print("\n=== WH2 da INIT-DRIFT-FIX-W2 qatorlari (2026-05-13) — quantity_after qiymatlari ===")
for r in q("""SELECT product_id, document_number, quantity_change, quantity_after, created_at, id
              FROM stock_movements WHERE document_number LIKE 'INIT-DRIFT-FIX-W2-%' ORDER BY product_id"""):
    print(f"  {dict(r)}")

print("\n=== Doc #101 har item: ledger SUM vs Stock vs jismoniy (drift xulosa) ===")
for it in q("SELECT warehouse_id,product_id,quantity FROM stock_adjustment_doc_items WHERE doc_id=101"):
    d=dict(it); wh,pid,phys=d['warehouse_id'],d['product_id'],d['quantity']
    led=q("SELECT COALESCE(SUM(quantity_change),0) s FROM stock_movements WHERE warehouse_id=? AND product_id=?",(wh,pid))[0]['s']
    st=q("SELECT quantity FROM stocks WHERE warehouse_id=? AND product_id=?",(wh,pid))[0]['quantity']
    pn=q("SELECT code,name FROM products WHERE id=?",(pid,))[0]
    print(f"  {pn['code']} {pn['name']}: jismoniy={phys} | Stock={st} | LedgerSUM={led} | Stock-Ledger drift={st-led}")

con.close(); os.remove(tmp); print("\nDONE")
