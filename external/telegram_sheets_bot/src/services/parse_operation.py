"""Telegram matnidan summa va kirim/chiqim turini sodda aniqlash."""
import re


def parse_operation_text(text: str) -> tuple[str | None, float | None, str | None]:
    """
    Qaytaradi: (turi: kirim|chiqim|None, summa|None, izoh_qisqa)
    """
    if not text or not text.strip():
        return None, None, None

    raw = text.strip()
    low = raw.lower()

    turi: str | None = None
    chiqim_kalit = (
        "chiqim",
        "berdim",
        "to'ladim",
        "to‘ladim",
        "toladim",
        "xarajat",
        "harajat",
        "to'lov",
        "berdim",
        "kamayt",
    )
    kirim_kalit = (
        "kirim",
        "oldim",
        "keldi",
        "qarz",
        "olding",
        "qo'sh",
        "qoʻsh",
    )
    if any(k in low for k in chiqim_kalit):
        turi = "chiqim"
    elif any(k in low for k in kirim_kalit):
        turi = "kirim"

    # Sonlar: 1 500 000, 500000, 500 ming
    summa: float | None = None
    for m in re.finditer(r"\d[\d\s,.]*", raw):
        chunk = m.group(0).replace(" ", "").replace(",", "").replace(".", "")
        if not chunk.isdigit():
            continue
        n = float(chunk)
        if n <= 0:
            continue
        summa = n
        break

    if summa and ("ming" in low or "минг" in low):
        if summa < 1_000_000:
            summa *= 1000

    izoh = raw[:200] if raw else None
    return turi, summa, izoh
