"""
Smoke testlar — refaktoringdan keyin ilova ishlashini tekshirish.
Server ishga tushirmasdan: pytest tests/test_smoke.py -v
"""
import pytest

pytest.importorskip("fastapi")


class TestAppLoads:
    """Ilova yuklanadi va asosiy yo‘llar ro‘yxatda."""

    def test_app_imports(self):
        from main import app
        assert app is not None
        assert app.title == "TOTLI HOLVA"

    def test_app_has_many_routes(self):
        from main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert len(routes) > 50, "Kamida 50 ta route bo‘lishi kerak"

    def test_ping_route_exists(self):
        from main import app
        paths = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path")]
        assert "/ping" in paths or any("/ping" in p for p in paths)

    def test_login_route_exists(self):
        from main import app
        paths = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path")]
        assert any("login" in p for p in paths)

    def test_favicon_route_exists(self):
        from main import app
        paths = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path")]
        assert "/favicon.ico" in paths


class TestRouterPaths:
    """Muhim router yo‘llari mavjudligini tekshirish."""

    def test_finance_route_exists(self):
        from main import app
        paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                paths.append(r.path)
        assert any("finance" in p for p in paths)

    def test_info_routes_registered(self):
        from main import app
        paths = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path")]
        assert any("info" in p for p in paths)

    def test_production_routes_registered(self):
        from main import app
        paths = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path")]
        assert any("production" in p for p in paths)
