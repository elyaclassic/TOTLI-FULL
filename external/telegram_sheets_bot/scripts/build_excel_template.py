"""
Excel shablon: Mijozlar + Operatsiyalar + Hisobot (qarzdorlik formulalari).
Ishga tushirish: python scripts/build_excel_template.py
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "templates" / "mijoz_hisob_kitobi.xlsx"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    wb = Workbook()
    op = wb.active
    op.title = "Operatsiyalar"
    headers = [
        "Sana",
        "Vaqt",
        "Mijoz_ID",
        "Mijoz_nomi",
        "Turi",
        "Summa",
        "Izoh",
        "Telegram_user",
        "Matn",
        "Manba",
    ]
    op.append(headers)
    for c in op[1]:
        c.font = Font(bold=True)
    mj = wb.create_sheet("Mijozlar")
    mj.append(["ID", "Nomi", "Telefon", "Boshlang'ich_qarz", "Mijoz_to'lagan", "Biz_bergan", "Qarz_qoldiq"])
    for c in mj[1]:
        c.font = Font(bold=True)

    # Qarz mantiqi:
    # kirim = mijoz to'lovi -> qarz kamayadi
    # chiqim = biz berdik -> qarz oshadi

    hs = wb.create_sheet("Hisobot")
    hs.append(["Ko'rsatkich", "Qiymat"])
    for c in hs[1]:
        c.font = Font(bold=True)
    hs["A2"] = "Mijozlar to'lagan"
    hs["B2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"kirim")'
    hs["A3"] = "Biz bergan"
    hs["B3"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"chiqim")'
    hs["A4"] = "Jami qarz qoldiq"
    hs["B4"] = "=B3-B2"
    hs["A5"] = "Operatsiyalar soni"
    hs["B5"] = '=COUNTA(Operatsiyalar!$A:$A)-1'
    hs["A7"] = "Izoh"
    hs["B7"] = "Bot: Mijozlar -> mijoz tanlash -> Mijoz to'ladi/Biz berdik -> summa; Hisobot -> tur -> davr -> bot/excel"

    wb.save(OUT)
    print(f"Yaratildi: {OUT}")


if __name__ == "__main__":
    main()
