"""Oddiy Excel (.xlsx) ga operatsiyalar yozish va hisobot formulalarini saqlash."""
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from src.config import EXCEL_FILE_PATH
from src.services.parse_operation import parse_operation_text

OPERATIONS_HEADERS = [
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

CUSTOMERS_HEADERS = ["ID", "Nomi", "Telefon", "Boshlang'ich", "Jami_kirim", "Jami_chiqim", "Qoldiq"]
SUMMARY_HEADERS = ["Ko'rsatkich", "Qiymat"]


def _excel_path() -> Path:
    p = Path(EXCEL_FILE_PATH).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _bold_first_row(ws) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True)


def _ensure_workbook() -> Path:
    path = _excel_path()
    if path.exists():
        return path

    wb = Workbook()

    ws = wb.active
    ws.title = "Operatsiyalar"
    ws.append(OPERATIONS_HEADERS)
    _bold_first_row(ws)

    customers = wb.create_sheet("Mijozlar")
    customers.append(CUSTOMERS_HEADERS)
    _bold_first_row(customers)

    summary = wb.create_sheet("Hisobot")
    summary.append(SUMMARY_HEADERS)
    _bold_first_row(summary)

    wb.save(path)
    return path


def _ensure_headers(ws, headers: list[str]) -> None:
    if not ws["A1"].value:
        ws.append(headers)
        _bold_first_row(ws)


def _ensure_summary_formulas(summary_ws, operations_ws) -> None:
    if not summary_ws["A2"].value:
        summary_ws["A2"] = "Jami kirim"
        summary_ws["B2"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"kirim")'
    if not summary_ws["A3"].value:
        summary_ws["A3"] = "Jami chiqim"
        summary_ws["B3"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"chiqim")'
    if not summary_ws["A4"].value:
        summary_ws["A4"] = "Farq"
        summary_ws["B4"] = "=B2-B3"
    if not summary_ws["A5"].value:
        summary_ws["A5"] = "Operatsiyalar soni"
        summary_ws["B5"] = '=COUNTA(Operatsiyalar!$A:$A)-1'


def _ensure_customer_formulas(customers_ws) -> None:
    for row in range(2, max(customers_ws.max_row, 2) + 1):
        if not customers_ws[f"A{row}"].value:
            continue
        customers_ws[f"E{row}"] = (
            f'=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A{row},Operatsiyalar!$E:$E,"kirim")'
        )
        customers_ws[f"F{row}"] = (
            f'=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A{row},Operatsiyalar!$E:$E,"chiqim")'
        )
        customers_ws[f"G{row}"] = f"=D{row}+E{row}-F{row}"


def append_operation_row(
    text: str,
    telegram_user_id: int,
    telegram_username: str | None,
    manba: str = "matn",
) -> str:
    """
    Lokal Excel ga yangi qator qo'shadi.
    Qaytadi: ishlatilgan fayl yo'li.
    """
    path = _ensure_workbook()
    wb = load_workbook(path)

    operations = wb["Operatsiyalar"] if "Operatsiyalar" in wb.sheetnames else wb.active
    operations.title = "Operatsiyalar"
    _ensure_headers(operations, OPERATIONS_HEADERS)

    if "Mijozlar" not in wb.sheetnames:
        wb.create_sheet("Mijozlar")
    customers = wb["Mijozlar"]
    _ensure_headers(customers, CUSTOMERS_HEADERS)

    if "Hisobot" not in wb.sheetnames:
        wb.create_sheet("Hisobot")
    summary = wb["Hisobot"]
    _ensure_headers(summary, SUMMARY_HEADERS)

    turi, summa, _ = parse_operation_text(text)
    now = __import__("datetime").datetime.now()
    uname = f"@{telegram_username}" if telegram_username else str(telegram_user_id)

    operations.append(
        [
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            "",
            "",
            turi or "",
            summa if summa is not None else "",
            "",
            uname,
            text[:5000],
            manba,
        ]
    )

    _ensure_customer_formulas(customers)
    _ensure_summary_formulas(summary, operations)
    wb.save(path)
    return str(path)


def append_voice_row(text: str, telegram_user_id: int, telegram_username: str | None) -> str:
    return append_operation_row(text, telegram_user_id, telegram_username, manba="ovoz")
