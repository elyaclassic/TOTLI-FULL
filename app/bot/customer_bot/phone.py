import re


def normalize_phone(raw):
    """Raqamni faqat raqamlarga keltirib, oxirgi 9 xonani (milliy qism) qaytaradi.

    +998905565959 / 998905565959 / "99899 652 82 60" -> oxirgi 9 raqam.
    9 raqamdan kam bo'lsa (soxta '0.....') -> None.
    """
    digits = re.sub(r"\D", "", raw or "")
    return digits[-9:] if len(digits) >= 9 else None
