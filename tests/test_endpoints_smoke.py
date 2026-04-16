"""HTTP smoke test — jonli serverga 15+ kritik endpoint so'rovini yuboradi.
Server ishga tushgan bo'lishi kerak (default: http://10.243.165.156:8080).

Ishga tushirish:
    python tests/test_endpoints_smoke.py
yoki:
    BASE_URL=http://localhost:8080 python tests/test_endpoints_smoke.py

Pytest:
    pytest tests/test_endpoints_smoke.py -v
"""
import os
import sys
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

BASE_URL = os.getenv("BASE_URL", "http://10.243.165.156:8080")
TIMEOUT = 5

# (path, kutilgan status koddari) — auth talab qilinadigan endpointlar 303 (redirect to /login)
ENDPOINTS = [
    ("/login", {200}),
    ("/", {303}),
    ("/sales/pos", {303}),
    ("/warehouse/transfers", {303}),
    ("/qoldiqlar", {303}),
    ("/finance", {303}),
    ("/production", {303}),
    ("/reports", {303}),
    ("/reports/profit", {303}),
    ("/reports/stock", {303}),
    ("/inventory", {303}),
    ("/employees", {303}),
    ("/supervisor/agent-orders", {303}),
    ("/api/agent/orders", {405}),  # GET method allowed emas
    ("/chat/api/unread-count", {303, 401}),
]


def _hit(path: str) -> int:
    url = BASE_URL.rstrip("/") + path
    try:
        req = Request(url, headers={"User-Agent": "totli-smoke/1.0"})
        # 3xx ni HTTPError sifatida ushlash uchun custom handler kerak emas
        # urllib default'da 3xx ni follow qilmaydi GET uchun (lekin urlopen qiladi).
        # Shuning uchun no_redirect_handler ishlataylik.
        from urllib.request import HTTPRedirectHandler, build_opener

        class _NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        opener = build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=TIMEOUT)
            return resp.status
        except HTTPError as e:
            return e.code
    except URLError as e:
        raise RuntimeError(f"Server javob bermadi: {url} ({e})")


def run_smoke() -> int:
    print(f"Smoke test: {BASE_URL}")
    print("-" * 60)
    failed = 0
    for path, expected in ENDPOINTS:
        try:
            code = _hit(path)
            ok = code in expected
            mark = "OK " if ok else "FAIL"
            print(f"  [{mark}] {code} {path}  (kutilgan: {sorted(expected)})")
            if not ok:
                failed += 1
        except Exception as e:
            print(f"  [ERR ] --- {path}  {e}")
            failed += 1
    print("-" * 60)
    if failed:
        print(f"NATIJA: {failed} ta xato")
        return 1
    print(f"NATIJA: barcha {len(ENDPOINTS)} endpoint OK")
    return 0


# ---- pytest moslashuvi ----
def test_endpoints_smoke():
    """pytest entry — server javob berishi uchun BASE_URL=... bilan ishlaydi."""
    import pytest
    try:
        _hit("/login")
    except RuntimeError as e:
        pytest.skip(f"Server ishlamayapti: {e}")
    rc = run_smoke()
    assert rc == 0, "Smoke test xatolar bilan tugadi"


if __name__ == "__main__":
    sys.exit(run_smoke())
