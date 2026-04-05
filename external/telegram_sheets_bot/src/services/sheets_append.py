"""Google Sheets — operatsiyalar qatori (hisob-kitob bazasi)."""
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from src.config import (
    GOOGLE_SHEET_ID,
    GOOGLE_SHEETS_CREDENTIALS_JSON,
    GOOGLE_SHEET_OPERATIONS_WORKSHEET,
)
from src.services.parse_operation import parse_operation_text

HEADERS = [
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


def _get_ws():
    cred_path = Path(GOOGLE_SHEETS_CREDENTIALS_JSON).expanduser()
    if not cred_path.is_file():
        raise RuntimeError(f"Service account fayli topilmadi: {cred_path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(cred_path), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID.strip())
    try:
        ws = sh.worksheet(GOOGLE_SHEET_OPERATIONS_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=GOOGLE_SHEET_OPERATIONS_WORKSHEET,
            rows=1000,
            cols=len(HEADERS),
        )
    return ws


def _ensure_headers(ws) -> None:
    try:
        a1 = ws.acell("A1").value
    except Exception:
        a1 = None
    if not a1:
        ws.insert_row(HEADERS, 1)


def append_operation_row(
    text: str,
    telegram_user_id: int,
    telegram_username: str | None,
    manba: str = "matn",
) -> None:
    """
    Operatsiyalar varag'iga qator: sana, vaqt, parse (turi, summa), telegram, matn.
    """
    if not GOOGLE_SHEETS_CREDENTIALS_JSON or not GOOGLE_SHEET_ID:
        raise RuntimeError("Google Sheets sozlanmagan (GOOGLE_SHEETS_CREDENTIALS_JSON yoki GOOGLE_SHEET_ID)")

    ws = _get_ws()
    _ensure_headers(ws)

    turi, summa, _iz = parse_operation_text(text)
    now = datetime.now(timezone.utc)
    sana = now.strftime("%Y-%m-%d")
    vaqt = now.strftime("%H:%M:%S")
    uname = f"@{telegram_username}" if telegram_username else str(telegram_user_id)

    ws.append_row(
        [
            sana,
            vaqt,
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


def append_voice_row(
    text: str,
    telegram_user_id: int,
    telegram_username: str | None,
) -> None:
    """Ovozdan keyin — manba=ovoz."""
    append_operation_row(text, telegram_user_id, telegram_username, manba="ovoz")
