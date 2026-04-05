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
    op.append(
        [
            "2026-04-05",
            "12:00:00",
            "1",
            "Namuna mijoz",
            "kirim",
            500000,
            "birinchi qator",
            "@user",
            "kirim 500 ming",
            "matn",
        ]
    )

    mj = wb.create_sheet("Mijozlar")
    mj.append(["ID", "Nomi", "Telefon", "Boshlang'ich_qarz", "Mijoz_to'lagan", "Biz_bergan", "Qarz_qoldiq"])
    for c in mj[1]:
        c.font = Font(bold=True)
    mj.append([1, "Namuna mijoz", "+998901234567", 0, None, None, None])
    mj.append([2, "Ikkinchi mijoz", "+998901112233", 100000, None, None, None])

    # Qarz mantiqi:
    # kirim = mijoz to'lovi -> qarz kamayadi
    # chiqim = biz berdik -> qarz oshadi
    mj["E2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A2,Operatsiyalar!$E:$E,"kirim")'
    mj["F2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A2,Operatsiyalar!$E:$E,"chiqim")'
    mj["G2"] = "=D2+F2-E2"

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
    hs["B7"] = "Bot tugmalari: Mijozlar -> mijoz tanlash -> Mijoz to'ladi/Biz berdik -> summa"

    wb.save(OUT)
    print(f"Yaratildi: {OUT}")


if __name__ == "__main__":
    main()
