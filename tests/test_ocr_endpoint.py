"""OCR web endpoint testi — /api/ocr/parse.

Endpoint funksiyasini to'g'ridan chaqiradi (DB ishlatmaydi, require_auth
Depends). TestClient o'rniga to'g'ridan — conftest in-memory SQLite StaticPool
muammosidan saqlanish uchun.
"""
import asyncio
import json
from unittest.mock import patch

from app.routes.api_ocr import ocr_parse
from app.services.ocr_service import OcrCliError


class _FakeUpload:
    def __init__(self, content_type, data, filename="doc.jpg"):
        self.content_type = content_type
        self.filename = filename
        self._data = data

    async def read(self):
        return self._data


def _run(upload):
    # Windows'da asyncio.run() ni ketma-ket chaqirish flaky (ProactorEventLoop
    # _ssock socket cleanup). Har test uchun yangi loop yaratib, to'g'ri yopamiz.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(ocr_parse(file=upload, current_user=None))
    finally:
        loop.close()


def _body(resp):
    return json.loads(resp.body)


def _fake_result():
    return {
        "hujjat_turi": "chek", "ishonch": "yuqori", "sana": "2026-06-11",
        "taminotchi": None, "valyuta": "UZS", "tolov_turi": "naqd",
        "qatorlar": [{"nomi": "Shakar", "miqdor": 50, "birlik": "kg", "narx": 12000, "summa": 600000}],
        "jami_summa": 600000, "ogohlantirish": None,
    }


def test_ocr_parse_ok():
    up = _FakeUpload("image/jpeg", b"\xff\xd8\xff fake jpeg")
    with patch("app.routes.api_ocr.extract_from_image", return_value=_fake_result()):
        resp = _run(up)
    body = _body(resp)
    assert body["ok"] is True
    assert body["data"]["jami_summa"] == 600000
    assert body["data"]["valyuta"] == "UZS"


def test_ocr_parse_cli_error():
    up = _FakeUpload("image/jpeg", b"fake")
    with patch("app.routes.api_ocr.extract_from_image", side_effect=OcrCliError("timeout")):
        resp = _run(up)
    body = _body(resp)
    assert body["ok"] is False
    assert "timeout" in body["error"].lower()


def test_ocr_parse_wrong_content_type():
    up = _FakeUpload("application/pdf", b"%PDF-1.4")
    resp = _run(up)  # extract chaqirilmaydi — content_type rad
    body = _body(resp)
    assert body["ok"] is False
    assert "rasm" in body["error"].lower()


def test_ocr_parse_empty_file():
    up = _FakeUpload("image/png", b"")
    resp = _run(up)
    body = _body(resp)
    assert body["ok"] is False
