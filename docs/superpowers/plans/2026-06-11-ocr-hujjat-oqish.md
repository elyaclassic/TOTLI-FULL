# OCR — Hujjatni rasmdan o'qish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hujjat (nakladnoy/chek/qo'lyozma/kvitansiya) rasmini Claude CLI Vision orqali o'qib strukturalangan JSON ga aylantirish, Telegram va web'dan inson tasdig'i bilan ishlatish.

**Architecture:** Yagona `ocr_service.py` yadrosi rasmni vaqtinchalik faylga saqlaydi, `claude --print` ni vision prompt bilan subprocess sifatida chaqiradi (`senior_bot/claude_client.py` patterni, ANTHROPIC_API_KEY olib tashlangan → Max obuna), javobdan JSON ajratib validatsiya qiladi. Telegram handler va web endpoint shu yadroni chaqiradi; natija hech qachon avtomatik saqlanmaydi — inson tasdiqlaydi.

**Tech Stack:** Python 3.13, FastAPI, aiogram 3.x, SQLite/SQLAlchemy, pytest, Claude CLI (Max obuna).

**Spec:** `docs/superpowers/specs/2026-06-11-ocr-hujjat-oqish-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `app/services/ocr_service.py` | 🆕 Yadro: `extract_from_image()` (CLI chaqirish) + `parse_ocr_json()` (toza parse/validatsiya) |
| `app/services/ocr_prompt.py` | 🆕 Vision prompt matni (yagona joy, DRY) |
| `tests/test_ocr_service.py` | 🆕 `parse_ocr_json` unit testlari |
| `app/routes/api_ocr.py` | 🆕 `POST /api/ocr/parse` — rasm upload → JSON |
| `tests/test_ocr_endpoint.py` | 🆕 endpoint testi (ocr_service mock) |
| `app/main.py` (yoki router ro'yxati) | ✏️ `api_ocr.router` ni include qilish |
| `app/templates/purchases/...` (create forma) | ✏️ "📷 Rasmdan to'ldirish" tugma + JS autofill |
| `app/bot/handlers/ocr.py` | 🆕 Telegram rasm handler + tasdiqlash FSM |
| `app/bot/main.py:25-27` | ✏️ `ocr.router` ni include qilish |

**Eslatma — backup:** Bu reja faqat YANGI fayllar qo'shadi va mavjud fayllarga kichik (router include, template tugma) o'zgarish kiritadi. DB sxemasi o'zgarmaydi. Mavjud fayl tahriridan oldin `.bak_pre_ocr_<sana>` backup oling (loyiha qoidasi).

---

## Task 1: Spike — Claude CLI Vision tasdiqlash (eng katta xavf)

**Maqsad:** `claude --print` rejimi rasmni Read tool orqali "ko'ra" oladimi — buni ISHGA tushirishdan OLDIN tasdiqlash. Agar ishlamasa, butun yondashuv qayta ko'riladi.

**Files:**
- Create: `scripts/spike_ocr_cli.py` (vaqtinchalik, sinovdan keyin o'chiriladi)

- [ ] **Step 1: Sinov rasmi tayyorlash**

Bitta haqiqiy hujjat rasmini (nakladnoy yoki chek) `scripts/sample_doc.jpg` ga qo'ying (telefondan oling yoki mavjud `app/static/images/products/` dan vaqtincha).

- [ ] **Step 2: Spike skript yozish**

```python
# scripts/spike_ocr_cli.py
"""Claude CLI vision tasdiqlash — rasmni o'qiy oladimi?"""
import os, subprocess, sys, shutil

img = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "scripts/sample_doc.jpg")
claude = shutil.which("claude") or os.path.expandvars(r"%APPDATA%\npm\claude.cmd")

prompt = (
    f"Quyidagi rasmni Read tool bilan o'qi: {img}\n"
    f"Rasmdagi BARCHA matnni (lotin/kirill/raqam) aynan o'qib ber. "
    f"Faqat o'qigan matnni qaytar, izoh yozma."
)
args = [claude, "--print", "--dangerously-skip-permissions", prompt]
if claude.lower().endswith((".cmd", ".bat")):
    args = ["cmd.exe", "/c"] + args

env = os.environ.copy()
env.pop("ANTHROPIC_API_KEY", None)  # Max obuna OAuth ishlasin

r = subprocess.run(args, capture_output=True, timeout=120, env=env)
print("RETURN:", r.returncode)
print("STDOUT:\n", r.stdout.decode("utf-8", "replace"))
print("STDERR:\n", r.stderr.decode("utf-8", "replace")[:500])
```

- [ ] **Step 3: Spike ishga tushirish**

Run: `python scripts/spike_ocr_cli.py scripts/sample_doc.jpg`
Expected: STDOUT da rasmdagi matn ko'rinadi (Claude Read tool bilan rasmni o'qiydi).

**Agar matn chiqsa** → yondashuv tasdiqlandi, Task 2 ga o'ting.
**Agar "cannot read image" / bo'sh chiqsa** → STOP. Foydalanuvchiga xabar bering: Claude CLI `--print` rejimida rasm o'qiy olmadi. Muqobil: rasmni base64 qilib prompt ichida berish yoki OpenAI vision API (telegram_sheets_bot kaliti). Yondashuvni qayta brainstorm qiling.

- [ ] **Step 4: Spike skriptni o'chirish (tasdiqlangach)**

```bash
git rm -f scripts/spike_ocr_cli.py 2>/dev/null; rm -f scripts/sample_doc.jpg
```

---

## Task 2: Vision prompt matni (`ocr_prompt.py`)

**Files:**
- Create: `app/services/ocr_prompt.py`

- [ ] **Step 1: Prompt fayl yaratish**

```python
# app/services/ocr_prompt.py
"""OCR vision prompt — yagona ta'rif (DRY)."""

OCR_SYSTEM_PROMPT = """Sen moliyaviy hujjatlarni o'qiydigan OCR yordamchisisan.
Quyidagi rasmni Read tool bilan o'qi: {image_path}

Rasm — ta'minotchi nakladnoyi, do'kon/bozor cheki, qo'lyozma daftar yoki
to'lov kvitansiyasi bo'lishi mumkin. Matn aralash bo'lishi mumkin
(lotin + kirill + raqam), jumladan qo'lyozma.

FAQAT quyidagi JSON ni qaytar. Hech qanday izoh, matn yoki ```json belgisi
yozma — sof JSON:

{{
  "hujjat_turi": "nakladnoy | chek | qolyozma | kvitansiya | nomalum",
  "ishonch": "yuqori | orta | past",
  "sana": "YYYY-MM-DD yoki null",
  "taminotchi": "matn yoki null",
  "valyuta": "UZS | USD",
  "tolov_turi": "naqd | otkazma | qarz | nomalum",
  "qatorlar": [
    {{"nomi": "...", "miqdor": 0, "birlik": "kg|dona|litr|...", "narx": 0, "summa": 0}}
  ],
  "jami_summa": 0,
  "ogohlantirish": "o'qib bo'lmagan/shubhali joylar izohi yoki null"
}}

QOIDALAR:
- Raqamlar SON sifatida (string emas), ajratuvchisiz: 600000 (600 000 emas).
- O'qib bo'lmagan joyni taxmin qilma — null qoldir va ogohlantirishda yoz.
- Agar shubhang bo'lsa "ishonch":"past" qil.
- Valyuta aniq ko'rinmasa, summalar katta (>100000) bo'lsa UZS deb hisobla.
- qatorlar har doim massiv (bitta qator bo'lsa ham)."""
```

- [ ] **Step 2: Commit**

```bash
git add app/services/ocr_prompt.py
git commit -m "feat(ocr): vision prompt matni (yagona ta'rif)"
```

---

## Task 3: JSON parse + validatsiya (`parse_ocr_json`)

Bu toza funksiya — tashqi bog'liqliksiz, TDD oson. Claude javobidan JSON
blokini ajratib oladi, validatsiya qiladi, default to'ldiradi.

**Files:**
- Create: `app/services/ocr_service.py`
- Test: `tests/test_ocr_service.py`

- [ ] **Step 1: Failing test yozish**

```python
# tests/test_ocr_service.py
import pytest
from app.services.ocr_service import parse_ocr_json, OcrParseError


def test_parse_clean_json():
    raw = '{"hujjat_turi":"chek","ishonch":"yuqori","sana":"2026-06-11",' \
          '"taminotchi":null,"valyuta":"UZS","tolov_turi":"naqd",' \
          '"qatorlar":[{"nomi":"Shakar","miqdor":50,"birlik":"kg","narx":12000,"summa":600000}],' \
          '"jami_summa":600000,"ogohlantirish":null}'
    r = parse_ocr_json(raw)
    assert r["hujjat_turi"] == "chek"
    assert r["valyuta"] == "UZS"
    assert r["qatorlar"][0]["miqdor"] == 50
    assert r["jami_summa"] == 600000


def test_parse_json_with_markdown_fence():
    raw = 'Mana natija:\n```json\n{"hujjat_turi":"nomalum","ishonch":"past",' \
          '"qatorlar":[],"jami_summa":0}\n```\nUmid qilaman foydali.'
    r = parse_ocr_json(raw)
    assert r["hujjat_turi"] == "nomalum"
    assert r["qatorlar"] == []


def test_parse_fills_defaults():
    raw = '{"hujjat_turi":"chek","qatorlar":[]}'
    r = parse_ocr_json(raw)
    assert r["ishonch"] == "past"        # default
    assert r["valyuta"] == "UZS"         # default
    assert r["tolov_turi"] == "nomalum"  # default
    assert r["jami_summa"] == 0


def test_parse_coerces_numbers():
    raw = '{"hujjat_turi":"chek","qatorlar":[{"nomi":"X","miqdor":"5","birlik":"kg","narx":"1000","summa":"5000"}],"jami_summa":"5000"}'
    r = parse_ocr_json(raw)
    assert r["qatorlar"][0]["miqdor"] == 5.0
    assert r["jami_summa"] == 5000.0


def test_parse_invalid_raises():
    with pytest.raises(OcrParseError):
        parse_ocr_json("bu umuman JSON emas, hech qanday qavs yo'q")
```

- [ ] **Step 2: Testni ishga tushirib, fail bo'lishini ko'rish**

Run: `python -m pytest tests/test_ocr_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.ocr_service`

- [ ] **Step 3: Minimal implementatsiya**

```python
# app/services/ocr_service.py
"""OCR yadro: Claude CLI Vision → strukturalangan JSON.

parse_ocr_json — toza parse/validatsiya (tashqi bog'liqliksiz, testlanadi).
extract_from_image — Claude CLI subprocess + parse (Task 4).
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
    # markdown fence tozalash
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return fence.group(1)
    # birinchi { dan oxirgi } gacha
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

    # son maydonlar
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
```

- [ ] **Step 4: Testlar o'tishini ko'rish**

Run: `python -m pytest tests/test_ocr_service.py -v`
Expected: 5 ta test PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/ocr_service.py tests/test_ocr_service.py
git commit -m "feat(ocr): JSON parse + validatsiya (parse_ocr_json) + testlar"
```

---

## Task 4: Claude CLI Vision chaqirish (`extract_from_image`)

**Files:**
- Modify: `app/services/ocr_service.py` (yangi funksiya qo'shish)
- Test: `tests/test_ocr_service.py` (subprocess mock bilan)

- [ ] **Step 1: Failing test yozish (mock bilan)**

`tests/test_ocr_service.py` oxiriga qo'shing:

```python
from unittest.mock import patch, MagicMock


def test_extract_from_image_success(tmp_path):
    img = tmp_path / "doc.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg")

    fake_cli_json = '{"result": "{\\"hujjat_turi\\":\\"chek\\",\\"qatorlar\\":[],\\"jami_summa\\":0}"}'
    fake = MagicMock(returncode=0, stdout=fake_cli_json.encode(), stderr=b"")

    with patch("app.services.ocr_service._sp.run", return_value=fake):
        from app.services.ocr_service import extract_from_image
        r = extract_from_image(str(img))
    assert r["hujjat_turi"] == "chek"


def test_extract_from_image_cli_fail(tmp_path):
    img = tmp_path / "doc.jpg"
    img.write_bytes(b"fake")
    fake = MagicMock(returncode=1, stdout=b"", stderr=b"some error")
    with patch("app.services.ocr_service._sp.run", return_value=fake):
        from app.services.ocr_service import extract_from_image, OcrCliError
        with pytest.raises(OcrCliError):
            extract_from_image(str(img))
```

- [ ] **Step 2: Testni ishga tushirib fail ko'rish**

Run: `python -m pytest tests/test_ocr_service.py::test_extract_from_image_success -v`
Expected: FAIL — `ImportError: cannot import name 'extract_from_image'`

- [ ] **Step 3: Implementatsiya (claude_client.py patterni)**

`app/services/ocr_service.py` boshiga import qo'shing:

```python
import os
import shutil
import subprocess as _sp
import sys
import logging

from app.services.ocr_prompt import OCR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_CLI_TIMEOUT = int(os.environ.get("OCR_CLI_TIMEOUT", "120"))
_OCR_MODEL = os.environ.get("OCR_MODEL", "claude-opus-4-8[1m]")


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
```

`app/services/ocr_service.py` oxiriga funksiya qo'shing:

```python
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

    # --print default text qaytaradi; ba'zan JSON envelope bo'lishi mumkin.
    text = out
    try:
        env_json = json.loads(out)
        if isinstance(env_json, dict) and "result" in env_json:
            text = env_json["result"]
    except json.JSONDecodeError:
        pass  # oddiy text — to'g'ridan-to'g'ri parse qilamiz

    return parse_ocr_json(text)
```

- [ ] **Step 4: Testlar o'tishini ko'rish**

Run: `python -m pytest tests/test_ocr_service.py -v`
Expected: barcha test PASS (7 ta).

- [ ] **Step 5: Commit**

```bash
git add app/services/ocr_service.py tests/test_ocr_service.py
git commit -m "feat(ocr): Claude CLI Vision chaqirish (extract_from_image)"
```

---

## Task 5: Web endpoint `POST /api/ocr/parse`

**Files:**
- Create: `app/routes/api_ocr.py`
- Test: `tests/test_ocr_endpoint.py`

- [ ] **Step 1: Failing test yozish (ocr_service mock)**

```python
# tests/test_ocr_endpoint.py
import io
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app  # mavjud FastAPI app

client = TestClient(app)


def _fake_result():
    return {
        "hujjat_turi": "chek", "ishonch": "yuqori", "sana": "2026-06-11",
        "taminotchi": None, "valyuta": "UZS", "tolov_turi": "naqd",
        "qatorlar": [{"nomi": "Shakar", "miqdor": 50, "birlik": "kg", "narx": 12000, "summa": 600000}],
        "jami_summa": 600000, "ogohlantirish": None,
    }


def test_ocr_parse_ok():
    img = io.BytesIO(b"\xff\xd8\xff fake jpeg")
    with patch("app.routes.api_ocr.extract_from_image", return_value=_fake_result()):
        resp = client.post(
            "/api/ocr/parse",
            files={"file": ("doc.jpg", img, "image/jpeg")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["jami_summa"] == 600000


def test_ocr_parse_cli_error():
    from app.services.ocr_service import OcrCliError
    img = io.BytesIO(b"fake")
    with patch("app.routes.api_ocr.extract_from_image", side_effect=OcrCliError("timeout")):
        resp = client.post("/api/ocr/parse", files={"file": ("d.jpg", img, "image/jpeg")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "timeout" in body["error"].lower()
```

> **Diqqat:** Agar `app.main` import qilinishi auth/DB talab qilsa, mavjud
> `tests/conftest.py` fikstura/auth bypass patternini ishlating (boshqa endpoint
> testlari, masalan `tests/test_endpoints_smoke.py` ga qarang).

- [ ] **Step 2: Fail ko'rish**

Run: `python -m pytest tests/test_ocr_endpoint.py -v`
Expected: FAIL — 404 (endpoint yo'q) yoki import xato.

- [ ] **Step 3: Endpoint implementatsiya**

```python
# app/routes/api_ocr.py
"""OCR web endpoint — rasm upload → strukturalangan JSON.

Natija HECH QACHON avtomatik saqlanmaydi — front-end forma uni ko'rsatadi,
foydalanuvchi tahrirlab odatdagi 'Saqlash' bilan yozadi.
"""
import os
import tempfile
import logging

from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import JSONResponse

from app.deps import require_auth
from app.models.database import User
from app.services.ocr_service import extract_from_image, OcrCliError, OcrParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["ocr"])

_ALLOWED = {"image/jpeg", "image/png", "image/webp"}
_MAX_BYTES = 12 * 1024 * 1024  # 12 MB


@router.post("/parse")
async def ocr_parse(
    file: UploadFile = File(...),
    current_user: User = Depends(require_auth),
):
    if file.content_type not in _ALLOWED:
        return JSONResponse({"ok": False, "error": "Faqat JPG/PNG/WEBP rasm"}, status_code=200)

    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        return JSONResponse({"ok": False, "error": "Rasm juda katta (>12MB)"}, status_code=200)

    suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
            tf.write(raw)
            tmp_path = tf.name
        data = extract_from_image(tmp_path)
        return JSONResponse({"ok": True, "data": data}, status_code=200)
    except (OcrCliError, OcrParseError) as e:
        logger.warning(f"[ocr] parse fail: {e}")
        return JSONResponse(
            {"ok": False, "error": f"O'qib bo'lmadi: {e}. Qayta urinib ko'ring yoki qo'lda kiriting."},
            status_code=200,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
```

- [ ] **Step 4: Router ni ro'yxatga olish**

`app/main.py` da boshqa `include_router` larni toping (masalan `app.include_router(purchases.router)`) va yoniga qo'shing:

```python
from app.routes import api_ocr
app.include_router(api_ocr.router)
```

> Aniq joyni topish: `grep -n "include_router" app/main.py`. Mavjud importlar va
> include tartibiga rioya qiling.

- [ ] **Step 5: Testlar o'tishini ko'rish**

Run: `python -m pytest tests/test_ocr_endpoint.py -v`
Expected: 2 ta test PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routes/api_ocr.py tests/test_ocr_endpoint.py app/main.py
git commit -m "feat(ocr): web endpoint POST /api/ocr/parse"
```

---

## Task 6: Web forma — "Rasmdan to'ldirish" tugma + JS autofill

**Maqsad:** Xarid yaratish formasida rasm yuklash tugmasi, `/api/ocr/parse`
chaqirib, forma maydonlarini avtomatik to'ldirish.

**Files:**
- Modify: xarid yaratish template (aniq fayl: `grep -rl "purchases" app/templates/ | xargs grep -l "form"` yoki `purchases.py` da `create`/`new` GET route qaysi template'ni `TemplateResponse` qilishini toping — loyiha qoidasi: route'dan tekshir).

- [ ] **Step 1: Forma template'ni topish va backup**

`app/routes/purchases.py` da xarid yaratish GET route (`/purchases/new` yoki shunga o'xshash) qaysi template'ni qaytarishini toping. O'sha template'ni backup qiling:

```bash
cp app/templates/<topilgan>.html app/templates/<topilgan>.html.bak_pre_ocr_20260611
```

- [ ] **Step 2: Tugma + fayl input qo'shish**

Forma boshiga (qatorlar jadvalidan oldin) qo'shing:

```html
<div class="ocr-upload" style="margin-bottom:12px;">
  <label class="btn btn-secondary" style="cursor:pointer;">
    📷 Rasmdan to'ldirish
    <input type="file" id="ocrFile" accept="image/*" capture="environment" hidden>
  </label>
  <span id="ocrStatus" style="margin-left:8px;color:#666;"></span>
</div>
```

- [ ] **Step 3: JS autofill skript qo'shish**

Template oxiriga (`{% block extra_js %}` ichiga — loyiha base.html shu blokni
ishlatadi; agar yo'q bo'lsa `<script>` to'g'ridan-to'g'ri) qo'shing:

```html
<script>
(function () {
  const fileInput = document.getElementById('ocrFile');
  const status = document.getElementById('ocrStatus');
  if (!fileInput) return;

  fileInput.addEventListener('change', async function () {
    const f = fileInput.files[0];
    if (!f) return;
    status.textContent = '⏳ O\'qiyapman...';
    const fd = new FormData();
    fd.append('file', f);
    try {
      const resp = await fetch('/api/ocr/parse', { method: 'POST', body: fd });
      const j = await resp.json();
      if (!j.ok) { status.textContent = '⚠️ ' + j.error; return; }
      fillForm(j.data);
      status.textContent = '✅ To\'ldirildi (' + j.data.ishonch + ' ishonch). Tekshiring!';
    } catch (e) {
      status.textContent = '⚠️ Xato: ' + e;
    } finally {
      fileInput.value = '';
    }
  });

  // TODO(learning): fillForm — forma maydon ID/name larini real template'ga
  // moslang. Quyida namuna; sizning forma strukturangizga moslashtiring.
  function fillForm(d) {
    const setIf = (sel, val) => {
      const el = document.querySelector(sel);
      if (el && val != null && val !== '') el.value = val;
    };
    setIf('[name="date"]', d.sana);
    setIf('[name="supplier_name"], [name="partner_name"]', d.taminotchi);
    // qatorlar jadvaliga qo'shish — formangizning "qator qo'shish" mantig'iga ulang.
    if (Array.isArray(d.qatorlar) && window.addPurchaseRow) {
      d.qatorlar.forEach(q => window.addPurchaseRow(q));
    }
    // past-ishonch joylarni vizual belgilash
    if (d.ishonch === 'past') {
      document.querySelectorAll('.ocr-fillable').forEach(el => el.style.background = '#fff3cd');
    }
  }
})();
</script>
```

- [ ] **Step 4: Qo'lda sinov**

Serverni qayta yuklang (loyiha runbook: taskkill + start.bat). Xarid yaratish
formasini oching → "📷 Rasmdan to'ldirish" → real chek rasmini tanlang →
maydonlar to'ladimi tekshiring. Past ishonch sariq fonda ko'rinsin.

- [ ] **Step 5: Commit**

```bash
git add app/templates/<topilgan>.html
git commit -m "feat(ocr): xarid formasida rasmdan to'ldirish tugmasi + autofill"
```

---

## Task 7: Telegram handler + tasdiqlash FSM (`bot/handlers/ocr.py`)

**Files:**
- Create: `app/bot/handlers/ocr.py`
- Modify: `app/bot/main.py:8,25` (import + include_router)

- [ ] **Step 1: Handler yozish**

```python
# app/bot/handlers/ocr.py
"""Telegram OCR — rasm yuboriladi, o'qiladi, foydalanuvchi tasdiqlaydi.

Oqim: foto keladi → ocr_service → natija matn + inline tugmalar
(✅ Tasdiqlash / ❌ Bekor). Tasdiqlangach natija FSM data'da saqlanadi
(keyingi bosqich: ops.py purchase FSM ga uzatish — bu reja qamrovidan tashqari,
hozir natija ko'rsatiladi va tasdiq holati saqlanadi)."""
from __future__ import annotations

import os
import tempfile
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.bot.handlers.ops_auth import is_ops_allowed
from app.services.ocr_service import extract_from_image, OcrCliError, OcrParseError

logger = logging.getLogger(__name__)
router = Router()


def _format_result(d: dict) -> str:
    lines = [f"<b>📄 Hujjat:</b> {d.get('hujjat_turi')}  •  ishonch: {d.get('ishonch')}"]
    if d.get("sana"):
        lines.append(f"📅 Sana: {d['sana']}")
    if d.get("taminotchi"):
        lines.append(f"🏷 Ta'minotchi: {d['taminotchi']}")
    lines.append(f"💱 Valyuta: {d.get('valyuta')}  •  To'lov: {d.get('tolov_turi')}")
    lines.append("")
    for q in d.get("qatorlar", []):
        lines.append(f"• {q['nomi']} — {q['miqdor']} {q['birlik']} × {q['narx']:g} = {q['summa']:g}")
    lines.append("")
    lines.append(f"<b>JAMI: {d.get('jami_summa'):g} {d.get('valyuta')}</b>")
    if d.get("ogohlantirish"):
        lines.append(f"\n⚠️ {d['ogohlantirish']}")
    return "\n".join(lines)


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="ocr:confirm"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="ocr:cancel"),
    ]])


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, bot: Bot):
    # Faqat ruxsatli foydalanuvchi (ops kabi)
    if not is_ops_allowed(message.from_user.id):
        return  # boshqa handlerlar ko'rsin / jim

    wait = await message.answer("⏳ Rasmni o'qiyapman, biroz kuting...")
    photo = message.photo[-1]  # eng katta o'lcham
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
            tmp_path = tf.name
        await bot.download(photo, destination=tmp_path)
        data = extract_from_image(tmp_path)
    except (OcrCliError, OcrParseError) as e:
        await wait.edit_text(f"⚠️ O'qib bo'lmadi: {e}\nQayta urinib ko'ring yoki qo'lda kiriting.")
        return
    except Exception as e:
        logger.exception("ocr photo fail")
        await wait.edit_text(f"⚠️ Kutilmagan xato: {type(e).__name__}")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    await state.update_data(ocr_result=data)
    await wait.edit_text(_format_result(data), reply_markup=_confirm_kb())


@router.callback_query(F.data == "ocr:confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext):
    data = (await state.get_data()).get("ocr_result")
    if not data:
        await cb.answer("Ma'lumot topilmadi", show_alert=True)
        return
    # Hozircha: tasdiqlandi xabari. Keyingi bosqich — ops purchase FSM ga uzatish.
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Tasdiqlandi</b>", reply_markup=None)
    await cb.answer("Tasdiqlandi")


@router.callback_query(F.data == "ocr:cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext):
    await state.update_data(ocr_result=None)
    await cb.message.edit_text("❌ Bekor qilindi", reply_markup=None)
    await cb.answer()
```

> **YAGNI eslatma:** Bu reja Telegram'da OCR natijani **ko'rsatish va
> tasdiqlash**ni qamraydi. Tasdiqlangan natijani to'g'ridan-to'g'ri xarid
> hujjatiga yozish (ops.py purchase FSM ga ulash) — alohida keyingi reja.
> Sabab: avval OCR aniqligini real hujjatlarda sinab ko'rish kerak.

- [ ] **Step 2: Router ro'yxatga olish**

`app/bot/main.py:8` import qatorini yangilang:

```python
from app.bot.handlers import start, reports, ops, ocr
```

`app/bot/main.py:25` (ops include'dan keyin) qo'shing:

```python
    _dp.include_router(ocr.router)
```

> **Tartib muhim:** `ocr.router` ni `start.router` dan OLDIN qo'ying (start'da
> keng `F.text` filtri bor). `F.photo` filtri tor, lekin tartib xavfsizligi uchun
> ops bilan birga oldinga qo'ying.

- [ ] **Step 3: Qo'lda sinov**

Botni qayta yuklang. Yordamchim botga real hujjat rasmini yuboring → natija
jadval + tugmalar chiqsin → ✅ Tasdiqlash ishlasin.

- [ ] **Step 4: Commit**

```bash
git add app/bot/handlers/ocr.py app/bot/main.py
git commit -m "feat(ocr): Telegram rasm handler + tasdiqlash"
```

---

## Task 8: Yakuniy sinov va hujjatlash

- [ ] **Step 1: To'liq test to'plami**

Run: `python -m pytest tests/test_ocr_service.py tests/test_ocr_endpoint.py -v`
Expected: barcha PASS.

> Eslatma: to'liq suite (`pytest`) Windows/Py3.13 da teardown'da flaky bo'lishi
> mumkin (loyiha memory: ProactorEventLoop _ssock GC) — OCR testlari alohida
> o'tsa yetarli.

- [ ] **Step 2: Smoke — server ko'tariladimi**

Run: `python -c "from app.main import app; print('OK', len(app.routes))"`
Expected: `OK <son>` (import xatosi yo'q).

- [ ] **Step 3: Real sinov ro'yxati (qo'lda)**

4 turdagi hujjat bilan sinang va natijani spec'dagi sxema bilan solishtiring:
- [ ] Ta'minotchi nakladnoyi (ko'p qator)
- [ ] Do'kon/bozor cheki
- [ ] Qo'lyozma daftar
- [ ] To'lov kvitansiyasi

Har biri uchun: hujjat turi to'g'ri aniqlandimi, valyuta to'g'rimi, raqamlar
to'g'rimi, past-ishonch joylar belgilandimi.

- [ ] **Step 4: Memory yangilash**

`MEMORY.md` ga bir qator qo'shing va topik fayl yarating
(`project_ocr_vision_<sana>.md`): yondashuv (Claude CLI Vision), kalit fayllar,
ANTHROPIC_API_KEY pop nuqtasi, qamrov tashqarisi (avto-yozish yo'q).

- [ ] **Step 5: Yakuniy commit**

```bash
git add MEMORY.md memory/
git commit -m "docs(ocr): OCR vision tizimi memory + sinov yakunlandi"
```

---

## Self-Review (reja muallifi tomonidan bajarildi)

- **Spec qamrovi:** ✅ Barcha hujjat turi (Claude auto-detect), aralash til
  (prompt), valyuta+to'lov turi (sxema), Telegram+web (Task 6,7), yagona yadro
  (Task 3,4), inson tasdig'i (Task 6 forma / Task 7 tugma), xato boshqaruvi
  (OcrCliError/OcrParseError har bosqichda).
- **Placeholder skani:** Web forma `fillForm` da bitta o'rinli TODO bor — bu
  ataylab (real forma maydon ID lari template topilganda ma'lum bo'ladi;
  learning contribution nuqtasi sifatida belgilangan).
- **Tip izchilligi:** `extract_from_image`, `parse_ocr_json`, `OcrCliError`,
  `OcrParseError` barcha tasklarda bir xil nomlanadi; `_sp` (subprocess alias)
  mock yo'li bilan mos.
- **Eng katta xavf:** Task 1 spike — Claude CLI `--print` vision. Reja shu
  tasdiqdan keyin davom etadi.
