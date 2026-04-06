import argparse
import difflib
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

from app.models.database import Agent, Partner, SessionLocal


NS = {"k": "http://www.opengis.net/kml/2.2"}
AGENT_MAP = {
    "Akbar": "Akbarjon",
}


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


def parse_kml(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    doc = root.find("k:Document", NS)
    if doc is None:
        raise ValueError("KML ichida Document topilmadi")

    rows = []
    for agent_folder in doc.findall("k:Folder", NS):
        raw_agent = (agent_folder.findtext("k:name", default="", namespaces=NS) or "").strip()
        agent_name = AGENT_MAP.get(raw_agent, raw_agent)
        for day_folder in agent_folder.findall("k:Folder", NS):
            day_name = (day_folder.findtext("k:name", default="", namespaces=NS) or "").strip()
            for pm in day_folder.findall("k:Placemark", NS):
                name = (pm.findtext("k:name", default="", namespaces=NS) or "").strip()
                if not name:
                    continue
                description = (pm.findtext("k:description", default="", namespaces=NS) or "").strip()
                coords = (pm.findtext(".//k:coordinates", default="", namespaces=NS) or "").strip()
                if not coords:
                    continue
                parts = [x.strip() for x in coords.split(",")]
                if len(parts) < 2:
                    continue
                try:
                    lng = float(parts[0])
                    lat = float(parts[1])
                except ValueError:
                    continue
                if lat == 0 and lng == 0:
                    continue
                rows.append({
                    "agent_name": agent_name,
                    "day_name": day_name,
                    "name": name,
                    "name_norm": norm_text(name),
                    "name_core": core_name(name),
                    "description": description,
                    "phone_norm": norm_phone(description),
                    "lat": lat,
                    "lng": lng,
                })
    return rows


def backup_db(db_path: Path) -> Path:
    backup_path = db_path.with_name(f"{db_path.stem}_backup_before_kml_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def build_indexes(db) -> tuple[dict, dict, dict]:
    agents = {a.id: a.full_name for a in db.query(Agent).all()}
    phone_index = defaultdict(list)
    name_agent_index = defaultdict(list)
    all_partners = db.query(Partner).all()

    for partner in all_partners:
        phone = norm_phone(partner.phone or "")
        if phone:
            phone_index[phone].append(partner)
        agent_name = agents.get(partner.agent_id, "")
        name_agent_index[(norm_text(partner.name or ""), agent_name)].append(partner)

    return agents, phone_index, name_agent_index


def resolve_ambiguous_phone(row: dict, candidates: list[Partner], agents: dict) -> tuple[Partner | None, str | None]:
    row_core = row["name_core"]
    if not row_core:
        return None, None

    exact = [p for p in candidates if core_name(p.name or "") == row_core]
    if len(exact) == 1:
        return exact[0], "phone+exact_name"

    contains = [
        p for p in candidates
        if row_core in core_name(p.name or "") or core_name(p.name or "") in row_core
    ]
    if len(contains) == 1:
        return contains[0], "phone+contains_name"

    scored = []
    for partner in candidates:
        partner_core = core_name(partner.name or "")
        ratio = difflib.SequenceMatcher(None, row_core, partner_core).ratio() if partner_core else 0.0
        if row["agent_name"] and agents.get(partner.agent_id, "") == row["agent_name"]:
            ratio += 0.05
        scored.append((ratio, partner))
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) >= 2:
        top_ratio, top_partner = scored[0]
        second_ratio = scored[1][0]
        if top_ratio >= 0.93 and (top_ratio - second_ratio) >= 0.08:
            return top_partner, "phone+fuzzy_name"
    elif len(scored) == 1 and scored[0][0] >= 0.93:
        return scored[0][1], "phone+fuzzy_name"
    return None, None


def match_rows(rows: list[dict], db):
    agents, phone_index, name_agent_index = build_indexes(db)
    matched = []
    stats = {
        "kml_rows": len(rows),
        "matched_unique_phone": 0,
        "matched_resolved_phone": 0,
        "matched_unique_name_agent": 0,
        "ambiguous_phone": 0,
        "ambiguous_name_agent": 0,
        "unmatched": 0,
        "already_had_location": 0,
    }

    for row in rows:
        candidates = []
        method = None

        if row["phone_norm"] and row["phone_norm"] in phone_index:
            candidates = phone_index[row["phone_norm"]]
            method = "phone"
        elif (row["name_norm"], row["agent_name"]) in name_agent_index:
            candidates = name_agent_index[(row["name_norm"], row["agent_name"])]
            method = "name+agent"

        if not candidates:
            stats["unmatched"] += 1
            continue
        if len(candidates) > 1:
            if method == "phone":
                resolved, resolved_method = resolve_ambiguous_phone(row, candidates, agents)
                if resolved is not None:
                    partner = resolved
                    method = resolved_method
                    stats["matched_resolved_phone"] += 1
                else:
                    stats["ambiguous_phone"] += 1
                    continue
            else:
                stats["ambiguous_name_agent"] += 1
                continue
        else:
            partner = candidates[0]
            if method == "phone":
                stats["matched_unique_phone"] += 1
            else:
                stats["matched_unique_name_agent"] += 1
        if partner.latitude is not None and partner.longitude is not None:
            stats["already_had_location"] += 1
        matched.append({
            "partner": partner,
            "method": method,
            "agent_name": agents.get(partner.agent_id, ""),
            "kml": row,
        })
    return matched, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kml", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--overwrite-existing", action="store_true")
    args = parser.parse_args()

    rows = parse_kml(Path(args.kml))
    db = SessionLocal()
    try:
        matched, stats = match_rows(rows, db)
        unique_partner_ids = {m["partner"].id for m in matched}
        updates = [
            m for m in matched
            if args.overwrite_existing or m["partner"].latitude is None or m["partner"].longitude is None
        ]

        print("SUMMARY")
        print({**stats, "unique_partners_matched": len(unique_partner_ids), "partners_to_update": len({m['partner'].id for m in updates})})
        print("SAMPLE_MATCHES")
        for item in matched[:20]:
            p = item["partner"]
            print({
                "method": item["method"],
                "partner_id": p.id,
                "partner_name": p.name,
                "agent": item["agent_name"],
                "phone": p.phone,
                "new_lat": item["kml"]["lat"],
                "new_lng": item["kml"]["lng"],
                "current_lat": p.latitude,
                "current_lng": p.longitude,
            })

        if not args.apply:
            print("DRY_RUN_ONLY")
            return 0

        db_path = Path("D:/TOTLI BI/totli_holva.db")
        backup_path = backup_db(db_path)
        updated_ids = set()
        for item in updates:
            partner = item["partner"]
            partner.latitude = item["kml"]["lat"]
            partner.longitude = item["kml"]["lng"]
            updated_ids.add(partner.id)
        db.commit()
        print("APPLIED")
        print({"updated_partners": len(updated_ids), "backup": str(backup_path)})
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
