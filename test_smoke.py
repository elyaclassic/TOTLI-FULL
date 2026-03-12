"""
Smoke test — refaktoringdan keyin ilova ishlashini tekshirish.
Server ishga tushirmasdan: app import va asosiy route’lar mavjudligi.
Ishga tushirish: pytest test_smoke.py -v   yoki  python test_smoke.py
"""
import sys


def test_app_imports():
    """Ilova va routerlar import bo‘lishi kerak."""
    from main import app
    assert app is not None
    assert app.title == "TOTLI HOLVA"


def test_app_has_routes():
    """Kamida asosiy route’lar ro‘yxatdan o‘tgan bo‘lishi kerak."""
    from main import app
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/ping" in paths
    assert "/login" in paths
    assert "/favicon.ico" in paths
    assert "/finance" in paths or any("/finance" in p for p in paths)
    assert len(paths) > 50


def test_ping_route_exists():
    """GET /ping route mavjud va GET qabul qiladi."""
    from main import app
    for r in app.routes:
        if hasattr(r, "path") and r.path == "/ping":
            assert "GET" in getattr(r, "methods", set()) or hasattr(r, "endpoint")
            return
    raise AssertionError("/ping route topilmadi")


def test_login_route_exists():
    """Login route mavjud."""
    from main import app
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert any("login" in p for p in paths)


def test_key_routers_mounted():
    """Asosiy routerlar ulangan: info, dashboard, auth, finance, qoldiqlar."""
    from main import app
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert any("/info" in p or p == "/info" for p in paths)
    assert any("/dashboard" in p for p in paths)
    assert any("/finance" in p or p == "/finance" for p in paths)
    assert any("/qoldiqlar" in p or p == "/qoldiqlar" for p in paths)


def test_production_and_sales_routes():
    """Ishlab chiqarish va savdo route’lari mavjud."""
    from main import app
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert any("/production" in p for p in paths)
    assert any("/sales" in p or "/purchases" in p for p in paths)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
