"""
Sales Doctor mijozlar balansini TOTLI BI ga import qilish.

Excel format:
  - "Название клиента" (mijoz nomi)
  - "Телефон" (telefon)
  - "Общий" (jami balans, sales doctor belgisi BILAN: manfiy=mijoz qarzdor, musbat=biz qarzdor)
  - "ИД клиента" (sales doctor ID, masalan a1_375)
  - "Агент" (agent ismi)

Mantiq:
  - Sales Doctor "Общий" -2,480,000 -> TOTLI BI partner.balance = +2,480,000 (mijoz qarzdor)
  - Sales Doctor +1,000,000 -> TOTLI BI partner.balance = -1,000,000 (biz qarzdormiz)
  - Belgi teskari!

Mijozni topish:
  1. Telefon orqali (normalize qilingan: 998xxx)
  2. Topilmasa, nom orqali (case-insensitive)
  3. Topilmasa, ro'yxat ga qo'shiladi (manual qaror)

Reja:
  --dry-run  : faqat tahlil, ro'yxat ko'rsatadi
  --execute  : haqiqiy import (backup + commit)

Saqlash usuli (har match):
  - partner.balance qiymati TO'G'RIDAN-TO'G'RI o'rnatiladi (Payment yaratilmaydi)
  - partner.notes ga qo'shiladi: "Sales doctor balansi: <amount> (<sd_id>) [import 04.05.2026]"
"""
import argparse
import re
import shutil
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("totli_holva.db")
BACKUP_DIR = Path("backups")
EXCEL_PATH = Path(r"C:\Users\elya_\Downloads\Балансы клиентов ( Нет срока ) - 04.05.2026 16_53_57.xlsx")


def normalize_phone(p):
    if not p or not isinstance(p, str):
        return None
    digits = re.sub(r"\D", "", p)
    # 998xxxxxxxxx (12 raqam)
    if len(digits) >= 12 and digits.startswith("998"):
        return digits[-12:]
    if len(digits) == 9:  # raqam o'zi (998 siz)
        return "998" + digits
    if len(digits) >= 9:
        return digits[-9:]
    return digits


def main(execute):
    if not EXCEL_PATH.exists():
        print(f"[XATO] Excel topilmadi: {EXCEL_PATH}")
        sys.exit(1)
    if not DB_PATH.exists():
        print(f"[XATO] DB topilmadi: {DB_PATH}")
        sys.exit(1)

    import pandas as pd
    df = pd.read_excel(EXCEL_PATH, engine="calamine")
    df.columns = [str(c).strip() for c in df.columns]
    print(f"Excel: {len(df)} qator yuklandi")

    if execute:
        BACKUP_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"totli_holva_pre_sd_import_{ts}.db"
        shutil.copy2(DB_PATH, backup_path)
        print(f"Backup: {backup_path}\n")

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Barcha aktiv partnerlarni xotiraga
    partners = cur.execute("SELECT id, code, name, phone, phone2, balance FROM partners WHERE is_active=1").fetchall()
    by_phone = {}
    by_name = {}
    for p in partners:
        for ph_field in ("phone", "phone2"):
            n = normalize_phone(p[ph_field])
            if n and n not in by_phone:
                by_phone[n] = p
        nm = (p["name"] or "").strip().lower()
        if nm and nm not in by_name:
            by_name[nm] = p

    print(f"TOTLI BI da {len(partners)} aktiv partner.\n")
    print("=" * 100)
    print(f"{'#':>3} {'Sales Doctor':25} {'Match':10} {'TOTLI BI partner':30} {'SD bal':>14} {'TOTLI yangi bal':>16}")
    print("=" * 100)

    matches = []
    not_found = []
    bal_col = next((c for c in df.columns if "Общий" in c), None)
    name_col = next((c for c in df.columns if "Название" in c), None)
    phone_col = next((c for c in df.columns if "Телефон" in c), None)
    sdid_col = next((c for c in df.columns if "ИД" in c and "клиента" in c), None)

    if not bal_col or not name_col:
        print("[XATO] 'Общий' yoki 'Название клиента' ustun topilmadi")
        sys.exit(1)

    for idx, row in df.iterrows():
        sd_name = str(row[name_col]).strip() if row[name_col] else ""
        sd_phone = normalize_phone(str(row[phone_col]) if phone_col and row[phone_col] else "")
        sd_id = str(row[sdid_col]) if sdid_col and row[sdid_col] else ""
        sd_bal = float(row[bal_col]) if row[bal_col] is not None else 0
        new_bal = -sd_bal  # belgi teskari

        # Topish
        match = None
        match_type = ""
        if sd_phone and sd_phone in by_phone:
            match = by_phone[sd_phone]
            match_type = "phone"
        elif sd_name.lower() in by_name:
            match = by_name[sd_name.lower()]
            match_type = "name"

        if match:
            matches.append({
                "row": idx + 2,
                "sd_name": sd_name,
                "sd_phone": sd_phone,
                "sd_id": sd_id,
                "sd_bal": sd_bal,
                "new_bal": new_bal,
                "partner": match,
                "match_type": match_type,
            })
            print(f"{idx+1:>3} {sd_name[:24]:25} {match_type:10} {match['name'][:29]:30} {sd_bal:>14,.0f} {new_bal:>16,.0f}")
        else:
            not_found.append({"row": idx + 2, "sd_name": sd_name, "sd_phone": sd_phone, "sd_id": sd_id, "sd_bal": sd_bal})
            no_match = "YO'Q"
            print(f"{idx+1:>3} {sd_name[:24]:25} {no_match:10} {'---':30} {sd_bal:>14,.0f} {'---':>16}")

    print("=" * 100)
    print(f"\nXulosa: {len(matches)} match, {len(not_found)} topilmadi (jami {len(df)})")
    print(f"Match summa: {sum(m['sd_bal'] for m in matches):,.0f} (sales doctor) -> {sum(m['new_bal'] for m in matches):,.0f} (TOTLI BI)")
    print(f"Yo'qotilgan summa: {sum(n['sd_bal'] for n in not_found):,.0f}\n")

    if not execute:
        print("[DRY-RUN] hech narsa o'zgarmadi (--execute bilan ishga tushiring)")
        if not_found:
            print(f"\nTopilmagan {len(not_found)} mijoz ro'yxati:")
            for n in not_found[:30]:
                print(f"  R{n['row']:3} sd={n['sd_id']:10} {n['sd_name'][:40]:40} bal={n['sd_bal']:>13,.0f}  tel={n['sd_phone'] or '-'}")
            if len(not_found) > 30:
                print(f"  ... yana {len(not_found)-30} ta")
        con.close()
        return

    # IJRO
    print("\n[IJRO] balans yangilanyapti...\n")
    cur.execute("BEGIN")
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        renamed = 0
        for m in matches:
            p = m["partner"]
            sd_name = m["sd_name"]
            cur_name = (p["name"] or "").strip()
            note_parts = [f"[SD-import {today}] sd_id={m['sd_id']} bal={m['sd_bal']:.0f} -> {m['new_bal']:.0f}"]

            if sd_name and sd_name.lower() != cur_name.lower():
                note_parts.append(f"name renamed: '{cur_name}' -> '{sd_name}'")
                cur.execute(
                    "UPDATE partners SET balance = ?, name = ?, notes = COALESCE(notes,'') || char(10) || ? WHERE id = ?",
                    (m["new_bal"], sd_name, " | ".join(note_parts), p["id"]),
                )
                renamed += 1
            else:
                cur.execute(
                    "UPDATE partners SET balance = ?, notes = COALESCE(notes,'') || char(10) || ? WHERE id = ?",
                    (m["new_bal"], note_parts[0], p["id"]),
                )
        print(f"[OK] {len(matches)} mijoz balansi yangilandi ({renamed} ta nomi sales doctor ga moslashtirildi)")

        # Yangi mijozlarni yaratish
        last_code = cur.execute("SELECT code FROM partners WHERE code LIKE 'P%' ORDER BY id DESC LIMIT 1").fetchone()
        try:
            next_seq = int((last_code[0] or "P0000").lstrip("P")) + 1
        except (ValueError, AttributeError):
            next_seq = 1
        created = 0
        for n in not_found:
            new_code = f"P{next_seq:04d}"
            next_seq += 1
            new_bal = -float(n["sd_bal"] or 0)
            phone = n["sd_phone"] or None
            notes = f"[SD-import {today}] yangi yaratildi. sd_id={n['sd_id']} bal={n['sd_bal']:.0f} -> {new_bal:.0f}"
            cur.execute(
                """INSERT INTO partners (code, name, type, phone, balance, is_active, notes, created_at)
                   VALUES (?, ?, 'customer', ?, ?, 1, ?, ?)""",
                (new_code, n["sd_name"], phone, new_bal, notes, datetime.now()),
            )
            created += 1
        print(f"[OK] {created} yangi mijoz yaratildi (kodlar P{next_seq-created:04d}..P{next_seq-1:04d})")

        con.commit()
        print(f"\n[YAKUN] Jami: {len(matches)} match yangilandi + {created} yangi yaratildi = {len(matches) + created} mijoz balansi import qilindi")
    except Exception as e:
        con.rollback()
        print(f"[XATO] {e}")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    args = p.parse_args()
    main(execute=args.execute)
