"""OCR yadro: Claude CLI Vision → strukturalangan JSON.

parse_ocr_json — toza parse/validatsiya (tashqi bog'liqliksiz, testlanadi).
extract_from_image — Claude CLI subprocess + parse.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess as _sp
import sys

from app.services.ocr_prompt import OCR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_CLI_TIMEOUT = int(os.environ.get("OCR_CLI_TIMEOUT", "120"))
_OCR_MODEL = os.environ.get("OCR_MODEL", "claude-opus-4-8[1m]")


class OcrParseError(Exception):
    """Claude javobidan haqiqiy JSON ajratib bo'lmadi."""


class OcrCliError(Exception):
    """Claude CLI chaqiruvi muvaffaqiyatsiz."""


def _resolve_claude_path() -> str:
    found = shutil.which("claude")
    if found:
        return found
    if sys.platform == "win32":
        for c in (
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            os.path.expandvars(r"%LOCALAPPDATA%\npm\claude.cmd"),
        ):
            if os.path.exists(c):
                return c
    return "claude"


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


def extract_from_image(image_path: str) -> dict:
    """Rasmni Claude CLI Vision orqali o'qib strukturalangan dict qaytaradi.

    Raises:
        OcrCliError — CLI topilmadi/timeout/xato qaytardi.
        OcrParseError — javobdan JSON ajratib bo'lmadi.
    """
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        raise OcrCliError(f"Rasm topilmadi: {abs_path}")

    prompt = OCR_SYSTEM_PROMPT.format(image_path=abs_path)
    claude_bin = _resolve_claude_path()
    args = [claude_bin, "--print", "--model", _OCR_MODEL,
            "--dangerously-skip-permissions", prompt]
    if sys.platform == "win32" and claude_bin.lower().endswith((".cmd", ".bat")):
        args = ["cmd.exe", "/c"] + args

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # Max obuna OAuth ishlasin

    try:
        result = _sp.run(
            args, stdout=_sp.PIPE, stderr=_sp.PIPE, stdin=_sp.DEVNULL,
            timeout=_CLI_TIMEOUT, env=env,
        )
    except _sp.TimeoutExpired as e:
        raise OcrCliError(f"Claude CLI vaqt tugadi ({_CLI_TIMEOUT}s)") from e
    except FileNotFoundError as e:
        raise OcrCliError("`claude` CLI topilmadi (server'da o'rnatilmagan)") from e

    out = (result.stdout or b"").decode("utf-8", "replace").strip()
    err = (result.stderr or b"").decode("utf-8", "replace").strip()
    if result.returncode != 0:
        logger.error(f"[ocr] CLI code={result.returncode} err={err[:300]}")
        raise OcrCliError(f"Claude xatosi (code={result.returncode}): {(err or out)[:200]}")

    text = out
    try:
        env_json = json.loads(out)
        if isinstance(env_json, dict) and "result" in env_json:
            text = env_json["result"]
    except json.JSONDecodeError:
        pass

    return parse_ocr_json(text)
