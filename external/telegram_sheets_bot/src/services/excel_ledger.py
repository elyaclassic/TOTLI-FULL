"""Oddiy Excel (.xlsx) ga operatsiyalar yozish va hisobot formulalarini saqlash."""
from datetime import datetime
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


def _num(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).replace(" ", "").replace(",", ""))
    except Exception:
        return 0.0


def _calc_customer_totals(operations_ws, customer_id: int) -> tuple[float, float]:
    kirim = 0.0
    chiqim = 0.0
    for row in range(2, operations_ws.max_row + 1):
        cid = operations_ws[f"C{row}"].value
        if not cid:
            continue
        try:
            if int(cid) != int(customer_id):
                continue
        except Exception:
            continue
        amount = _num(operations_ws[f"F{row}"].value)
        op_type = str(operations_ws[f"E{row}"].value or "").strip().lower()
        if op_type == "kirim":
            kirim += amount
        elif op_type == "chiqim":
            chiqim += amount
    return kirim, chiqim


def _load_book():
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

    return path, wb, operations, customers, summary


def list_customers() -> list[dict]:
    path, wb, operations, customers, _summary = _load_book()
    _ensure_customer_formulas(customers)
    wb.save(path)

    items: list[dict] = []
    for row in range(2, customers.max_row + 1):
        cid = customers[f"A{row}"].value
        name = customers[f"B{row}"].value
        if not cid or not name:
            continue
        kirim, chiqim = _calc_customer_totals(operations, int(cid))
        opening = _num(customers[f"D{row}"].value)
        items.append(
            {
                "id": int(cid),
                "name": str(name),
                "phone": str(customers[f"C{row}"].value or ""),
                "opening": opening,
                "kirim": kirim,
                "chiqim": chiqim,
                "qoldiq": opening + kirim - chiqim,
            }
        )
    return items


def get_customer(customer_id: int) -> dict | None:
    for item in list_customers():
        if item["id"] == customer_id:
            return item
    return None


def add_customer(name: str, phone: str = "", opening_balance: float = 0) -> dict:
    path, wb, _operations, customers, _summary = _load_book()

    max_id = 0
    for row in range(2, customers.max_row + 1):
        cid = customers[f"A{row}"].value
        if cid:
            max_id = max(max_id, int(cid))
    new_id = max_id + 1

    customers.append([new_id, name.strip(), phone.strip(), float(opening_balance or 0), None, None, None])
    _ensure_customer_formulas(customers)
    wb.save(path)
    return get_customer(new_id) or {"id": new_id, "name": name.strip(), "phone": phone.strip()}


def customer_history(customer_id: int, limit: int = 20) -> list[dict]:
    _path, _wb, operations, _customers, _summary = _load_book()
    rows: list[dict] = []
    for row in range(2, operations.max_row + 1):
        cid = operations[f"C{row}"].value
        if not cid:
            continue
        try:
            if int(cid) != int(customer_id):
                continue
        except Exception:
            continue
        rows.append(
            {
                "date": str(operations[f"A{row}"].value or ""),
                "time": str(operations[f"B{row}"].value or ""),
                "customer_id": int(customer_id),
                "customer_name": str(operations[f"D{row}"].value or ""),
                "type": str(operations[f"E{row}"].value or ""),
                "amount": float(operations[f"F{row}"].value or 0),
                "note": str(operations[f"G{row}"].value or ""),
                "telegram_user": str(operations[f"H{row}"].value or ""),
                "text": str(operations[f"I{row}"].value or ""),
                "source": str(operations[f"J{row}"].value or ""),
            }
        )
    return rows[-limit:]


def summary_report() -> dict:
    path, wb, operations, customers, summary = _load_book()
    _ensure_customer_formulas(customers)
    _ensure_summary_formulas(summary, operations)
    wb.save(path)
    jami_kirim = 0.0
    jami_chiqim = 0.0
    operatsiyalar_soni = max(0, operations.max_row - 1)
    for row in range(2, operations.max_row + 1):
        amount = _num(operations[f"F{row}"].value)
        op_type = str(operations[f"E{row}"].value or "").strip().lower()
        if op_type == "kirim":
            jami_kirim += amount
        elif op_type == "chiqim":
            jami_chiqim += amount
    return {
        "jami_kirim": jami_kirim,
        "jami_chiqim": jami_chiqim,
        "farq": jami_kirim - jami_chiqim,
        "operatsiyalar_soni": operatsiyalar_soni,
    }


def append_operation_row(
    text: str,
    telegram_user_id: int,
    telegram_username: str | None,
    manba: str = "matn",
    customer_id: int | None = None,
    customer_name: str | None = None,
    operation_type: str | None = None,
    amount: float | None = None,
    note: str | None = None,
) -> str:
    """
    Lokal Excel ga yangi qator qo'shadi.
    Qaytadi: ishlatilgan fayl yo'li.
    """
    path, wb, operations, customers, summary = _load_book()

    turi, summa, izoh = parse_operation_text(text)
    now = datetime.now()
    uname = f"@{telegram_username}" if telegram_username else str(telegram_user_id)
    if operation_type:
        turi = operation_type
    if amount is not None:
        summa = amount
    if note:
        izoh = note
    if customer_id and not customer_name:
        customer = get_customer(customer_id)
        if customer:
            customer_name = customer["name"]

    operations.append(
        [
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            customer_id or "",
            customer_name or "",
            turi or "",
            summa if summa is not None else "",
            izoh or "",
            uname,
            text[:5000],
            manba,
        ]
    )

    _ensure_customer_formulas(customers)
    _ensure_summary_formulas(summary, operations)
    wb.save(path)
    return str(path)


def append_voice_row(
    text: str,
    telegram_user_id: int,
    telegram_username: str | None,
    customer_id: int | None = None,
    customer_name: str | None = None,
    operation_type: str | None = None,
    amount: float | None = None,
    note: str | None = None,
) -> str:
    return append_operation_row(
        text,
        telegram_user_id,
        telegram_username,
        manba="ovoz",
        customer_id=customer_id,
        customer_name=customer_name,
        operation_type=operation_type,
        amount=amount,
        note=note,
    )
