"""Sales Doctor Excel'dan partner balansini TOTLI BI'ga import.

Har mijoz uchun:
  boshlang'ich_qarz = Excel.Общий - tizim_orderlar_qarz

Bu farq partner_balance_doc.items.balance ga yoziladi. Tizim balansni
hisoblaganda: oxirgi balance_doc + mavjud_orderlar_debt = Excel qiymati.
"""
import sqlite3
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

XLSX = r"C:\Users\elya_\Downloads\Балансы клиентов ( Нет срока ) - 07.05.2026 13_25_25.xlsx"
DB = Path(__file__).resolve().parent.parent / "totli_holva.db"
NS = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def normalize_phone(p):
    return re.sub(r"\D", "", str(p)) if p else ""


def parse_xlsx(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        with z.open("xl/sharedStrings.xml") as f:
            tree = ET.parse(f)
            for si in tree.getroot().findall("a:si", NS):
                texts = [t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
                shared.append("".join(texts))
        rows = []
        with z.open("xl/worksheets/sheet1.xml") as f:
            tree = ET.parse(f)
            sd = tree.getroot().find("a:sheetData", NS)
            for row in sd.findall("a:row", NS):
                cells = {}
                for c in row.findall("a:c", NS):
                    ref = c.get("r")
                    col = re.match(r"([A-Z]+)", ref).group(1)
                    t = c.get("t", "n")
                    v = c.find("a:v", NS)
                    if v is None:
                        cells[col] = ""
                        continue
                    val = v.text or ""
                    if t == "s":
                        cells[col] = shared[int(val)]
                    else:
                        try:
                            cells[col] = float(val)
                        except (ValueError, TypeError):
                            cells[col] = val
                rows.append(cells)
        return rows


def main():
    rows = parse_xlsx(XLSX)
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    # Partner mapping
    cur.execute("SELECT id, name, phone FROM partners WHERE is_active=1")
    phone_map, name_map = {}, {}
    for pid, name, phone in cur.fetchall():
        np = normalize_phone(phone)
        if np:
            phone_map[np] = pid
        if name:
            name_map[name.strip().lower()] = pid

    def system_balance(pid):
        cur.execute(
            """SELECT COALESCE(SUM(CASE WHEN type='return_sale' THEN -debt ELSE debt END), 0)
               FROM orders WHERE partner_id=? AND status NOT IN ('cancelled')""",
            (pid,),
        )
        return -float(cur.fetchone()[0] or 0)

    items_to_create = []
    for r in rows[1:]:
        name = (r.get("C") or "").strip()
        phone = r.get("J") or ""
        excel_total = float(r.get("L") or 0)
        if not name:
            continue
        np = normalize_phone(phone)
        pid = phone_map.get(np) or name_map.get(name.lower())
        if not pid:
            continue
        sys_bal = system_balance(pid)
        opening_balance = excel_total - sys_bal  # boshlang'ich farq
        if abs(opening_balance) < 1:
            continue  # mos keladi, kerak emas
        items_to_create.append((pid, name, opening_balance, sys_bal))

    if not items_to_create:
        print("Hech qanday yangilanish kerak emas")
        return 0

    print(f"Yaratiladi: {len(items_to_create)} ta partner uchun boshlang'ich balans")

    # KNT raqami
    today = datetime.now()
    prefix = f"KNT-{today.strftime('%Y%m%d')}"
    cur.execute("SELECT number FROM partner_balance_docs WHERE number LIKE ? ORDER BY id DESC LIMIT 1", (f"{prefix}-%",))
    last = cur.fetchone()
    try:
        seq = int(last[0].split("-")[-1]) + 1 if last else 1
    except (ValueError, IndexError):
        seq = 1
    number = f"{prefix}-{seq:04d}"

    # Doc yaratish
    cur.execute(
        """INSERT INTO partner_balance_docs (number, date, user_id, status, created_at)
           VALUES (?, ?, 1, 'confirmed', ?)""",
        (number, today, today),
    )
    doc_id = cur.lastrowid

    # Items
    total_balance = 0.0
    for pid, name, opening, prev in items_to_create:
        cur.execute(
            """INSERT INTO partner_balance_doc_items (doc_id, partner_id, balance, previous_balance)
               VALUES (?, ?, ?, ?)""",
            (doc_id, pid, opening, prev),
        )
        total_balance += opening

    conn.commit()
    print(f"\n✅ {number} (id={doc_id})")
    print(f"   Items: {len(items_to_create)}")
    print(f"   Jami boshlang'ich qarz: {total_balance:,.0f} so'm")
    print(f"\nTekshirish: /qoldiqlar/kontragent-balans yoki SQL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
