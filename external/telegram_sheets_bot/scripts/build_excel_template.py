"""
Excel shablon: Mijozlar + Operatsiyalar + Hisobot (formulalar).
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
    mj.append(["ID", "Nomi", "Telefon", "Boshlang'ich", "Jami_kirim", "Jami_chiqim", "Qoldiq"])
    for c in mj[1]:
        c.font = Font(bold=True)
    mj.append([1, "Namuna mijoz", "+998901234567", 0, None, None, None])
    mj.append([2, "Ikkinchi mijoz", "+998901112233", 100000, None, None, None])

    # Formulalar: Operatsiyalar!F = Summa, C = Mijoz_ID, E = Turi
    mj["E2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A2,Operatsiyalar!$E:$E,"kirim")'
    mj["F2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A2,Operatsiyalar!$E:$E,"chiqim")'
    mj["G2"] = "=D2+E2-F2"

    hs = wb.create_sheet("Hisobot")
    hs.append(["Ko'rsatkich", "Qiymat"])
    for c in hs[1]:
        c.font = Font(bold=True)
    hs["A2"] = "Jami kirim"
    hs["B2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"kirim")'
    hs["A3"] = "Jami chiqim"
    hs["B3"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"chiqim")'
    hs["A4"] = "Farq"
    hs["B4"] = "=B2-B3"
    hs["A5"] = "Operatsiyalar soni"
    hs["B5"] = '=COUNTA(Operatsiyalar!$A:$A)-1'
    hs["A7"] = "Izoh"
    hs["B7"] = "Bot tugmalari: Mijozlar -> mijoz tanlash -> Kirim/Chiqim -> summa"

    wb.save(OUT)
    print(f"Yaratildi: {OUT}")


if __name__ == "__main__":
    main()
