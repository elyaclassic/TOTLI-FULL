"""OCR yadro: Claude CLI Vision → strukturalangan JSON.

parse_ocr_json — toza parse/validatsiya (tashqi bog'liqliksiz, testlanadi).
extract_from_image — Claude CLI subprocess + parse.
"""
from __future__ import annotations

import json
import re


class OcrParseError(Exception):
    """Claude javobidan haqiqiy JSON ajratib bo'lmadi."""


_DEFAULTS = {
    "hujjat_turi": "nomalum",
    "ishonch": "past",
    "sana": None,
    "taminotchi": None,
    "valyuta": "UZS",
    "tolov_turi": "nomalum",
    "qatorlar": [],
    "jami_summa": 0,
    "ogohlantirish": None,
}


def _to_num(v):
    """String/None ni songa aylantirish (xato → 0)."""
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return 0


def _extract_json_block(raw: str) -> str:
    """Matn ichidan birinchi {...} blokini ajratib oladi."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise OcrParseError(f"JSON blok topilmadi: {raw[:120]}")
    return raw[start : end + 1]


def parse_ocr_json(raw: str) -> dict:
    """Claude javobidan strukturalangan dict — default + son validatsiya."""
    block = _extract_json_block(raw)
    try:
        data = json.loads(block)
    except json.JSONDecodeError as e:
        raise OcrParseError(f"JSON parse xato: {e}") from e
    if not isinstance(data, dict):
        raise OcrParseError("JSON obyekt emas")

    out = dict(_DEFAULTS)
    out.update({k: v for k, v in data.items() if k in _DEFAULTS})

    out["jami_summa"] = _to_num(out.get("jami_summa"))
    qatorlar = out.get("qatorlar") or []
    norm = []
    for q in qatorlar:
        if not isinstance(q, dict):
            continue
        norm.append({
            "nomi": str(q.get("nomi") or "").strip(),
            "miqdor": _to_num(q.get("miqdor")),
            "birlik": str(q.get("birlik") or "").strip(),
            "narx": _to_num(q.get("narx")),
            "summa": _to_num(q.get("summa")),
        })
    out["qatorlar"] = norm
    return out
