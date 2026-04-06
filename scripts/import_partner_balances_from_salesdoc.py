import argparse
import csv
import difflib
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

from app.models.database import Agent, Partner, PartnerBalanceDoc, PartnerBalanceDocItem, SessionLocal


NS_MAIN = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def norm_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 9 else digits


def norm_text(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("ʻ", "'").replace("ʼ", "'").replace("`", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def core_name(value: str) -> str:
    text = re.sub(r"\+?\d[\d\s-]{6,}", " ", value or "")
    return norm_text(text)


def parse_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    items = []
    for si in root.findall("main:si", NS_MAIN):
        texts = []
        for t in si.iterfind(".//main:t", NS_MAIN):
            texts.append(t.text or "")
        items.append("".join(texts))
    return items


def cell_value(cell, shared_strings: list[str]):
    cell_type = cell.get("t")
    value_el = cell.find("main:v", NS_MAIN)
    value = value_el.text if value_el is not None else None
    if cell_type == "s" and value is not None:
        return shared_strings[int(value)]
    if cell_type == "inlineStr":
        text_el = cell.find(".//main:t", NS_MAIN)
        return text_el.text if text_el is not None else ""
    return value


def parse_salesdoc_xlsx(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as zf:
        shared_strings = parse_shared_strings(zf)
        root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))

    rows = []
    sheet_data = root.find("main:sheetData", NS_MAIN)
    if sheet_data is None:
        return rows

    headers = None
    for row in sheet_data.findall("main:row", NS_MAIN):
        cells = {}
        for cell in row.findall("main:c", NS_MAIN):
            ref = cell.get("r", "")
            col = re.sub(r"\d+", "", ref)
            cells[col] = cell_value(cell, shared_strings)

        ordered = [cells.get(col, "") for col in [chr(code) for code in range(ord("A"), ord("Z") + 1)]]
        if headers is None:
            headers = ordered
            continue
        if not any(v not in (None, "") for v in ordered):
            continue

        client_name = (ordered[2] or "").strip()
        phone = (ordered[9] or "").strip()
        agent = (ordered[23] or "").strip()
        try:
            total_balance = float(ordered[11] or 0)
        except (TypeError, ValueError):
            total_balance = 0.0
        if not client_name:
            continue
        rows.append({
            "client_id": (ordered[1] or "").strip(),
            "name": client_name,
            "name_norm": norm_text(client_name),
            "name_core": core_name(client_name),
            "address": (ordered[8] or "").strip(),
            "phone_raw": phone,
            "phone_norm": norm_phone(phone),
            "agent": agent,
            "balance_external": total_balance,
            "visit": (ordered[7] or "").strip(),
            "territory": (ordered[6] or "").strip(),
            "comment": (ordered[10] or "").strip(),
        })
    return rows


def build_indexes(db):
    agents = {a.id: a.full_name for a in db.query(Agent).all()}
    phone_index = defaultdict(list)
    name_index = defaultdict(list)
    for partner in db.query(Partner).filter(Partner.is_active == True).all():
        phone = norm_phone(partner.phone or "")
        if phone:
            phone_index[phone].append(partner)
        name_index[core_name(partner.name or "")].append(partner)
    return agents, phone_index, name_index


def resolve_candidates(row, candidates, agents):
    row_core = row["name_core"]
    exact = [p for p in candidates if core_name(p.name or "") == row_core]
    if len(exact) == 1:
        return exact[0], "exact_name"

    same_agent = [p for p in candidates if agents.get(p.agent_id, "") == row["agent"]]
    if len(same_agent) == 1:
        return same_agent[0], "same_agent"

    contains = [p for p in candidates if row_core and (row_core in core_name(p.name or "") or core_name(p.name or "") in row_core)]
    if len(contains) == 1:
        return contains[0], "contains_name"

    scored = []
    for partner in candidates:
        ratio = difflib.SequenceMatcher(None, row_core, core_name(partner.name or "")).ratio()
        if agents.get(partner.agent_id, "") == row["agent"]:
            ratio += 0.05
        scored.append((ratio, partner))
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) >= 2 and scored[0][0] >= 0.93 and scored[0][0] - scored[1][0] >= 0.08:
        return scored[0][1], "fuzzy_name"
    if len(scored) == 1 and scored[0][0] >= 0.93:
        return scored[0][1], "fuzzy_name"
    return None, None


def match_rows(rows, db):
    agents, phone_index, name_index = build_indexes(db)
    matched = []
    unmatched = []
    ambiguous = []

    for row in rows:
        candidates = []
        method = None
        if row["phone_norm"] and row["phone_norm"] in phone_index:
            candidates = phone_index[row["phone_norm"]]
            method = "phone"
        elif row["name_core"] and row["name_core"] in name_index:
            candidates = name_index[row["name_core"]]
            method = "name"

        if not candidates:
            unmatched.append(row)
            continue
        if len(candidates) == 1:
            matched.append((row, candidates[0], method))
            continue

        resolved, submethod = resolve_candidates(row, candidates, agents)
        if resolved is not None:
            matched.append((row, resolved, f"{method}+{submethod}"))
        else:
            ambiguous.append((row, candidates))

    return matched, unmatched, ambiguous


def backup_db(db_path: Path) -> Path:
    backup_path = db_path.with_name(f"{db_path.stem}_backup_before_partner_balance_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def export_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Client ID", "Name", "Phone", "Agent", "Address", "External Balance"])
        for row in rows:
            w.writerow([row["client_id"], row["name"], row["phone_raw"], row["agent"], row["address"], row["balance_external"]])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--invert-sign", action="store_true")
    parser.add_argument("--doc-date")
    args = parser.parse_args()

    rows = parse_salesdoc_xlsx(Path(args.xlsx))
    db = SessionLocal()
    try:
        matched, unmatched, ambiguous = match_rows(rows, db)
        deltas = []
        for row, partner, method in matched:
            external = float(row["balance_external"] or 0)
            target_balance = -external if args.invert_sign else external
            current_balance = float(partner.balance or 0)
            delta = target_balance - current_balance
            deltas.append({
                "row": row,
                "partner": partner,
                "method": method,
                "external": external,
                "target": target_balance,
                "current": current_balance,
                "delta": delta,
            })

        to_apply = [d for d in deltas if abs(d["delta"]) > 0.0001]
        print("SUMMARY")
        print({
            "xlsx_rows": len(rows),
            "matched": len(matched),
            "unmatched": len(unmatched),
            "ambiguous": len(ambiguous),
            "to_apply": len(to_apply),
            "sum_external": round(sum(d["external"] for d in deltas), 2),
            "sum_target": round(sum(d["target"] for d in deltas), 2),
            "sum_current": round(sum(d["current"] for d in deltas), 2),
            "sum_delta": round(sum(d["delta"] for d in to_apply), 2),
            "invert_sign": args.invert_sign,
        })
        print("SAMPLE")
        for item in deltas[:20]:
            print({
                "partner_id": item["partner"].id,
                "partner_name": item["partner"].name,
                "method": item["method"],
                "external": item["external"],
                "current": item["current"],
                "target": item["target"],
                "delta": item["delta"],
            })

        export_csv(ROOT / "salesdoc_partner_balance_unmatched.csv", unmatched)
        export_csv(ROOT / "salesdoc_partner_balance_ambiguous.csv", [r for r, _ in ambiguous])

        if not args.apply:
            print("DRY_RUN_ONLY")
            return 0

        db_path = ROOT / "totli_holva.db"
        backup_path = backup_db(db_path)
        doc_date = datetime.now()
        if args.doc_date:
            doc_date = datetime.strptime(args.doc_date, "%Y-%m-%d")

        count = db.query(PartnerBalanceDoc).filter(
            PartnerBalanceDoc.date >= doc_date.replace(hour=0, minute=0, second=0),
            PartnerBalanceDoc.date < doc_date.replace(hour=23, minute=59, second=59),
        ).count()
        number = f"KNT-{doc_date.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"
        doc = PartnerBalanceDoc(number=number, date=doc_date, status="draft")
        db.add(doc)
        db.flush()

        for item in to_apply:
            db.add(PartnerBalanceDocItem(
                doc_id=doc.id,
                partner_id=item["partner"].id,
                balance=item["delta"],
            ))
        db.commit()

        for item in doc.items:
            partner = db.query(Partner).filter(Partner.id == item.partner_id).first()
            if partner:
                item.previous_balance = partner.balance
                partner.balance = float(partner.balance or 0) + float(item.balance or 0)
        doc.status = "confirmed"
        db.commit()

        print("APPLIED")
        print({
            "doc_id": doc.id,
            "doc_number": doc.number,
            "items": len(doc.items),
            "backup": str(backup_path),
        })
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
