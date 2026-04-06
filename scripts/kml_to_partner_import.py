import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl


NS = {"k": "http://www.opengis.net/kml/2.2"}
DAY_MAP = {
    "понедельник": 1,
    "вторник": 2,
    "среда": 3,
    "четверг": 4,
    "пятница": 5,
    "суббота": 6,
    "воскресенье": 0,
}
AGENT_MAP = {
    "Akbar": "Akbarjon",
}


def split_description(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text:
        return "", ""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return "", ""
    phone = ""
    address_parts = parts
    candidate = re.sub(r"[^\d+]", "", parts[0])
    digits = re.sub(r"\D", "", candidate)
    if len(digits) >= 7:
        phone = candidate
        address_parts = parts[1:]
    return phone, ", ".join(address_parts)


def parse_kml(input_path: Path) -> list[list]:
    root = ET.parse(input_path).getroot()
    doc = root.find("k:Document", NS)
    if doc is None:
        raise ValueError("KML ichida Document topilmadi")

    rows = []
    for agent_folder in doc.findall("k:Folder", NS):
        agent_name = (agent_folder.findtext("k:name", default="", namespaces=NS) or "").strip()
        if not agent_name:
            continue
        agent_name = AGENT_MAP.get(agent_name, agent_name)

        for day_folder in agent_folder.findall("k:Folder", NS):
            day_name = (day_folder.findtext("k:name", default="", namespaces=NS) or "").strip()
            visit_day = DAY_MAP.get(day_name.lower())

            for pm in day_folder.findall("k:Placemark", NS):
                name = (pm.findtext("k:name", default="", namespaces=NS) or "").strip()
                if not name:
                    continue

                description = (pm.findtext("k:description", default="", namespaces=NS) or "").strip()
                phone, address = split_description(description)
                coords_text = (pm.findtext(".//k:coordinates", default="", namespaces=NS) or "").strip()

                lat = ""
                lng = ""
                if coords_text:
                    parts = [p.strip() for p in coords_text.split(",")]
                    if len(parts) >= 2:
                        try:
                            lng_val = float(parts[0])
                            lat_val = float(parts[1])
                            if not (lat_val == 0 and lng_val == 0):
                                lat = lat_val
                                lng = lng_val
                        except ValueError:
                            pass

                note_parts = [f"KML agent: {agent_name}", f"KML kun: {day_name}"]
                if description and address != description:
                    note_parts.append(f"Asl izoh: {description}")

                rows.append([
                    name,
                    "customer",
                    phone,
                    address,
                    0,
                    0,
                    agent_name,
                    visit_day if visit_day is not None else "",
                    lat,
                    lng,
                    " | ".join(note_parts),
                ])
    return rows


def write_xlsx(rows: list[list], output_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Partners Import"
    ws.append([
        "Nomi",
        "Turi",
        "Telefon",
        "Manzil",
        "Kredit Limit",
        "Chegirma %",
        "Agent",
        "Tashrif kuni",
        "Latitude",
        "Longitude",
        "Izoh",
    ])
    for row in rows:
        ws.append(row)

    widths = {
        "A": 30,
        "B": 12,
        "C": 18,
        "D": 35,
        "E": 14,
        "F": 12,
        "G": 18,
        "H": 12,
        "I": 14,
        "J": 14,
        "K": 40,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(output_path)


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python scripts/kml_to_partner_import.py <input.kml> <output.xlsx>")
        return 1

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    rows = parse_kml(input_path)
    write_xlsx(rows, output_path)
    print(f"Created: {output_path}")
    print(f"Rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
