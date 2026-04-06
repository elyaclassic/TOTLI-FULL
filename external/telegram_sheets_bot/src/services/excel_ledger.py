"""Oddiy Excel (.xlsx) ga operatsiyalar yozish va hisobot formulalarini saqlash."""
from datetime import date, datetime
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

CUSTOMERS_HEADERS = ["ID", "Nomi", "Telefon", "Boshlang'ich_qarz", "Mijoz_to'lagan", "Biz_bergan", "Qarz_qoldiq"]
SUMMARY_HEADERS = ["Ko'rsatkich", "Qiymat"]


def _excel_path() -> Path:
    p = Path(EXCEL_FILE_PATH).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _bold_first_row(ws) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True)


def _find_header_row(ws, first_header: str) -> int | None:
    for row in range(1, min(ws.max_row, 20) + 1):
        value = str(ws[f"A{row}"].value or "").strip()
        if value == first_header:
            return row
    return None


def _next_data_row(
    ws,
    first_header: str,
    default_header_row: int = 1,
    data_columns: tuple[int, ...] | None = None,
) -> int:
    header_row = _find_header_row(ws, first_header) or default_header_row
    check_columns = data_columns or tuple(range(1, ws.max_column + 1))
    row = header_row + 1
    while row <= ws.max_row:
        if any(ws.cell(row=row, column=col).value not in (None, "") for col in check_columns):
            row += 1
            continue
        break
    return row


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
    header_row = _find_header_row(ws, headers[0])
    if header_row:
        return
    if not ws["A1"].value:
        ws.append(headers)
        _bold_first_row(ws)
        return
    for idx, header in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=header)
    _bold_first_row(ws)


def _ensure_summary_formulas(summary_ws, operations_ws) -> None:
    header_row = _find_header_row(summary_ws, SUMMARY_HEADERS[0]) or 1
    base_row = header_row + 1
    if not summary_ws[f"A{base_row}"].value:
        summary_ws[f"A{base_row}"] = "Mijozlar to'lagan"
        summary_ws[f"B{base_row}"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"kirim")'
    if not summary_ws[f"A{base_row + 1}"].value:
        summary_ws[f"A{base_row + 1}"] = "Biz bergan"
        summary_ws[f"B{base_row + 1}"] = '=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$E:$E,"chiqim")'
    if not summary_ws[f"A{base_row + 2}"].value:
        summary_ws[f"A{base_row + 2}"] = "Jami qarz qoldiq"
        summary_ws[f"B{base_row + 2}"] = f"=B{base_row + 1}-B{base_row}"
    if not summary_ws[f"A{base_row + 3}"].value:
        summary_ws[f"A{base_row + 3}"] = "Operatsiyalar soni"
        summary_ws[f"B{base_row + 3}"] = '=COUNTA(Operatsiyalar!$A:$A)-3'


def _ensure_customer_formulas(customers_ws) -> None:
    header_row = _find_header_row(customers_ws, CUSTOMERS_HEADERS[0]) or 1
    for row in range(header_row + 1, max(customers_ws.max_row, header_row + 1) + 1):
        if not customers_ws[f"A{row}"].value:
            continue
        customers_ws[f"E{row}"] = (
            f'=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A{row},Operatsiyalar!$E:$E,"kirim")'
        )
        customers_ws[f"F{row}"] = (
            f'=SUMIFS(Operatsiyalar!$F:$F,Operatsiyalar!$C:$C,A{row},Operatsiyalar!$E:$E,"chiqim")'
        )
        customers_ws[f"G{row}"] = f"=D{row}+F{row}-E{row}"


def _num(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).replace(" ", "").replace(",", ""))
    except Exception:
        return 0.0


def _int_or_none(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        return None
    except Exception:
        return None


def _calc_customer_totals(operations_ws, customer_id: int) -> tuple[float, float]:
    kirim = 0.0
    chiqim = 0.0
    header_row = _find_header_row(operations_ws, OPERATIONS_HEADERS[0]) or 1
    for row in range(header_row + 1, operations_ws.max_row + 1):
        cid = _int_or_none(operations_ws[f"C{row}"].value)
        if cid is None:
            continue
        if cid != int(customer_id):
            continue
        amount = _num(operations_ws[f"F{row}"].value)
        op_type = str(operations_ws[f"E{row}"].value or "").strip().lower()
        if op_type == "kirim":
            kirim += amount
        elif op_type == "chiqim":
            chiqim += amount
    return kirim, chiqim


def _match_period(row_date: str, period: str) -> bool:
    if period == "all":
        return True
    try:
        d = datetime.strptime(str(row_date), "%Y-%m-%d").date()
    except Exception:
        return False
    today = date.today()
    if period == "today":
        return d == today
    if period == "this_month":
        return d.year == today.year and d.month == today.month
    return True


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
    header_row = _find_header_row(customers, CUSTOMERS_HEADERS[0]) or 1
    for row in range(header_row + 1, customers.max_row + 1):
        cid = _int_or_none(customers[f"A{row}"].value)
        name = customers[f"B{row}"].value
        if cid is None or not name:
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
                "qoldiq": opening + chiqim - kirim,
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
    header_row = _find_header_row(customers, CUSTOMERS_HEADERS[0]) or 1
    for row in range(header_row + 1, customers.max_row + 1):
        cid = _int_or_none(customers[f"A{row}"].value)
        if cid is not None:
            max_id = max(max_id, cid)
    new_id = max_id + 1

    target_row = _next_data_row(
        customers,
        CUSTOMERS_HEADERS[0],
        default_header_row=header_row,
        data_columns=(1, 2, 3, 4),
    )
    customers[f"A{target_row}"] = new_id
    customers[f"B{target_row}"] = name.strip()
    customers[f"C{target_row}"] = phone.strip()
    customers[f"D{target_row}"] = float(opening_balance or 0)
    _ensure_customer_formulas(customers)
    wb.save(path)
    return get_customer(new_id) or {"id": new_id, "name": name.strip(), "phone": phone.strip()}


def customer_history(customer_id: int, limit: int = 20) -> list[dict]:
    _path, _wb, operations, _customers, _summary = _load_book()
    rows: list[dict] = []
    header_row = _find_header_row(operations, OPERATIONS_HEADERS[0]) or 1
    for row in range(header_row + 1, operations.max_row + 1):
        cid = _int_or_none(operations[f"C{row}"].value)
        if cid is None:
            continue
        if cid != int(customer_id):
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


def customer_history_by_period(customer_id: int, period: str = "all", limit: int = 50) -> list[dict]:
    rows = customer_history(customer_id, limit=10000)
    filtered = [row for row in rows if _match_period(row["date"], period)]
    return filtered[-limit:]


def summary_report_by_period(period: str = "all") -> dict:
    _path, _wb, operations, _customers, _summary = _load_book()
    jami_kirim = 0.0
    jami_chiqim = 0.0
    operatsiyalar_soni = 0
    header_row = _find_header_row(operations, OPERATIONS_HEADERS[0]) or 1
    for row in range(header_row + 1, operations.max_row + 1):
        row_date = str(operations[f"A{row}"].value or "")
        if not _match_period(row_date, period):
            continue
        operatsiyalar_soni += 1
        amount = _num(operations[f"F{row}"].value)
        op_type = str(operations[f"E{row}"].value or "").strip().lower()
        if op_type == "kirim":
            jami_kirim += amount
        elif op_type == "chiqim":
            jami_chiqim += amount
    return {
        "jami_kirim": jami_kirim,
        "jami_chiqim": jami_chiqim,
        "farq": jami_chiqim - jami_kirim,
        "operatsiyalar_soni": operatsiyalar_soni,
    }


def customer_report_by_period(customer_id: int, period: str = "all") -> dict | None:
    customer = get_customer(customer_id)
    if not customer:
        return None
    history = customer_history_by_period(customer_id, period, limit=1000)
    kirim = sum(float(item["amount"] or 0) for item in history if item["type"] == "kirim")
    chiqim = sum(float(item["amount"] or 0) for item in history if item["type"] == "chiqim")
    return {
        "customer": customer,
        "history": history[-20:],
        "period": period,
        "kirim": kirim,
        "chiqim": chiqim,
        "farq": customer.get("opening", 0) + chiqim - kirim,
    }


def export_report_excel(report_type: str, period: str = "all", customer_id: int | None = None) -> str:
    out_dir = _excel_path().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"hisobot_{report_type}_{period}_{ts}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Hisobot"

    if report_type == "summary":
        report = summary_report_by_period(period)
        ws.append(["Ko'rsatkich", "Qiymat"])
        ws.append(["Mijozlar to'lagan", report["jami_kirim"]])
        ws.append(["Biz bergan", report["jami_chiqim"]])
        ws.append(["Qarz qoldiq", report["farq"]])
        ws.append(["Operatsiyalar soni", report["operatsiyalar_soni"]])
    else:
        report = customer_report_by_period(int(customer_id or 0), period)
        if not report:
            raise RuntimeError("Mijoz topilmadi")
        customer = report["customer"]
        ws.append(["Mijoz", customer["name"]])
        ws.append(["Telefon", customer.get("phone") or ""])
        ws.append(["Mijoz to'lagan", report["kirim"]])
        ws.append(["Biz bergan", report["chiqim"]])
        ws.append(["Qarz qoldiq", report["farq"]])
        ws.append([])
        ws.append(["Sana", "Vaqt", "Turi", "Summa", "Izoh"])
        for item in report["history"]:
            ws.append([item["date"], item["time"], item["type"], item["amount"], item["note"]])

    for cell in ws[1]:
        cell.font = Font(bold=True)
    wb.save(path)
    return str(path)


def summary_report() -> dict:
    path, wb, operations, customers, summary = _load_book()
    _ensure_customer_formulas(customers)
    _ensure_summary_formulas(summary, operations)
    wb.save(path)
    jami_kirim = 0.0
    jami_chiqim = 0.0
    header_row = _find_header_row(operations, OPERATIONS_HEADERS[0]) or 1
    operatsiyalar_soni = 0
    for row in range(header_row + 1, operations.max_row + 1):
        if not any(operations.cell(row=row, column=col).value not in (None, "") for col in range(1, operations.max_column + 1)):
            continue
        operatsiyalar_soni += 1
        amount = _num(operations[f"F{row}"].value)
        op_type = str(operations[f"E{row}"].value or "").strip().lower()
        if op_type == "kirim":
            jami_kirim += amount
        elif op_type == "chiqim":
            jami_chiqim += amount
    return {
        "jami_kirim": jami_kirim,
        "jami_chiqim": jami_chiqim,
        "farq": jami_chiqim - jami_kirim,
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

    target_row = _next_data_row(
        operations,
        OPERATIONS_HEADERS[0],
        data_columns=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    )
    values = [
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
    for idx, value in enumerate(values, start=1):
        operations.cell(row=target_row, column=idx, value=value)

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
