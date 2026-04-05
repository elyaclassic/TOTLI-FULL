"""Google Sheets — qator qo'shish (service account)."""
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from src.config import GOOGLE_SHEET_ID, GOOGLE_SHEETS_CREDENTIALS_JSON, GOOGLE_SHEET_WORKSHEET


def append_voice_row(
    text: str,
    telegram_user_id: int,
    telegram_username: str | None,
) -> None:
    """Jadvalga: vaqt (UTC), user id, @username, matn."""
    if not GOOGLE_SHEETS_CREDENTIALS_JSON or not GOOGLE_SHEET_ID:
        raise RuntimeError("Google Sheets sozlanmagan (GOOGLE_SHEETS_CREDENTIALS_JSON yoki GOOGLE_SHEET_ID)")

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
        ws = sh.worksheet(GOOGLE_SHEET_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.sheet1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    uname = f"@{telegram_username}" if telegram_username else ""
    ws.append_row([ts, str(telegram_user_id), uname, text])
