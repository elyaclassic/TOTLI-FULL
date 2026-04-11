"""
Tier C1 + C2 refactor natijasini tekshiruvchi smoke testlar.

Har yangi modul:
1. Import qilinadi (syntax OK)
2. Router object mavjud
3. Kutilgan endpoint soni
4. Asosiy endpoint path'lar mavjud

pytest tests/test_refactor_modules.py -v
"""
import os
import pytest

# .env yuklash (boshqa import'lar SECRET_KEY ga muhtoj)
from dotenv import load_dotenv
load_dotenv()

pytest.importorskip("fastapi")


class TestTierC1EmployeesModules:
    """Tier C1 — employees.py 6 ta modulga bo'lindi."""

    def test_employees_core_imports(self):
        from app.routes.employees import router
        paths = [r.path for r in router.routes]
        assert "/employees" in paths
        assert "/employees/add" in paths
        assert "/employees/edit/{employee_id}" in paths
        assert "/employees/delete/{employee_id}" in paths
        assert "/employees/export" in paths

    def test_employees_dismissals(self):
        from app.routes.employees_dismissals import router
        paths = [r.path for r in router.routes]
        assert "/employees/dismissal/create" in paths
        assert "/employees/dismissal/{doc_id}" in paths
        assert "/employees/dismissal/{doc_id}/export-word" in paths
        assert len(router.routes) == 4

    def test_employees_advances(self):
        from app.routes.employees_advances import router
        paths = [r.path for r in router.routes]
        assert "/employees/advances" in paths
        assert "/employees/advance-docs" in paths
        assert "/employees/advances/add" in paths
        assert "/employees/advances/edit/{advance_id}" in paths
        assert "/employees/advances/bulk-delete" in paths
        assert len(router.routes) == 13

    def test_employees_attendance(self):
        from app.routes.employees_attendance import router
        paths = [r.path for r in router.routes]
        assert "/employees/attendance" in paths
        assert "/employees/attendance/form" in paths
        assert "/employees/attendance/form/save" in paths
        assert "/employees/attendance/form/confirm" in paths
        assert "/employees/attendance/records" in paths
        assert "/employees/attendance/records/bulk-delete" in paths
        assert len(router.routes) == 17

    def test_employees_salary(self):
        from app.routes.employees_salary import router
        paths = [r.path for r in router.routes]
        assert "/employees/salary" in paths
        assert "/employees/salary/save" in paths
        assert "/employees/salary/mark-paid/{employee_id}" in paths
        assert len(router.routes) == 3

    def test_employees_employment(self):
        from app.routes.employees_employment import router
        paths = [r.path for r in router.routes]
        assert "/employees/hiring-docs" in paths
        assert "/employees/hiring-doc/create" in paths
        assert "/employees/hiring-doc/{doc_id}" in paths
        assert "/employees/hiring-doc/{doc_id}/contract" in paths
        assert "/employees/hiring-doc/{doc_id}/contract/export-word" in paths
        assert "/employees/hiring-doc/{doc_id}/delete" in paths
        assert len(router.routes) == 13


class TestTierC2ApiModules:
    """Tier C2 — api_routes.py 6 ta modulga bo'lindi."""

    def test_api_system(self):
        from app.routes.api_system import router
        paths = [r.path for r in router.routes]
        assert "/api/pwa/config" in paths
        assert "/api/app/version" in paths
        assert "/api/app/download" in paths
        assert len(router.routes) == 3

    def test_api_dashboard(self):
        from app.routes.api_dashboard import router
        paths = [r.path for r in router.routes]
        assert "/api/stats" in paths
        assert "/api/products" in paths
        assert "/api/partners" in paths
        assert "/api/agents/locations" in paths
        assert "/api/drivers/locations" in paths
        assert "/api/notifications/unread" in paths
        assert "/api/notifications/{notification_id}/read" in paths
        assert len(router.routes) == 7

    def test_api_auth(self):
        from app.routes.api_auth import router
        paths = [r.path for r in router.routes]
        assert "/api/login" in paths
        assert "/api/agent/login" in paths
        assert "/api/agent/set-pin" in paths
        assert "/api/driver/login" in paths
        assert len(router.routes) == 4

    def test_api_auth_helpers(self):
        """Helper'lar ishlaydimi (login logika uchun kritik)."""
        from app.routes.api_auth import (
            _role_dashboard_url, _normalize_phone, _get_phone_variants,
        )
        # Role URL'lar
        assert _role_dashboard_url("admin") == "/"
        assert _role_dashboard_url("manager") == "/sales"
        assert _role_dashboard_url("unknown") == "/production/orders"
        # Phone normalize
        assert _normalize_phone("901234567") == "+998901234567"
        assert _normalize_phone("998901234567") == "+998901234567"
        assert _normalize_phone("+998901234567") == "+998901234567"
        # Variants
        variants = _get_phone_variants("+998901234567")
        assert "+998901234567" in variants
        assert "998901234567" in variants

    def test_api_driver_ops(self):
        from app.routes.api_driver_ops import router
        paths = [r.path for r in router.routes]
        assert "/api/driver/deliveries" in paths
        assert "/api/driver/delivery/{delivery_id}/status" in paths
        assert "/api/driver/stats" in paths
        assert "/api/driver/location" in paths
        assert len(router.routes) == 4

    def test_api_agent_ops(self):
        from app.routes.api_agent_ops import router
        paths = [r.path for r in router.routes]
        assert "/api/agent/orders" in paths
        assert "/api/agent/partners" in paths
        assert "/api/agent/visits" in paths
        assert "/api/agent/visit/checkin" in paths
        assert "/api/agent/visit/checkout" in paths
        assert "/api/agent/my-partners" in paths
        assert "/api/agent/products" in paths
        assert "/api/agent/order/create" in paths
        assert "/api/agent/my-orders" in paths
        assert "/api/agent/stats" in paths
        assert len(router.routes) == 16

    def test_api_agent_advanced(self):
        from app.routes.api_agent_advanced import router
        paths = [r.path for r in router.routes]
        assert "/api/agent/partner/{partner_id}/debts" in paths
        assert "/api/agent/reports/summary" in paths
        assert "/api/agent/partner/{partner_id}/reconciliation" in paths
        assert "/api/agent/kpi" in paths
        assert "/api/agent/tasks" in paths
        assert "/api/agent/tasks/{task_id}/complete" in paths
        assert "/api/agent/order/{order_id}/update" in paths
        assert "/api/agent/return/create" in paths
        assert "/api/agent/payment/create" in paths
        assert "/api/agent/payments" in paths
        assert len(router.routes) == 12


class TestDocumentService:
    """Tier B1-B2 — document_service.py qo'shilgan service layer."""

    def test_document_service_imports(self):
        from app.services.document_service import (
            DocumentError,
            confirm_purchase_atomic,
            revert_purchase_atomic,
            delete_purchase_fully,
            delete_sale_fully,
        )
        assert DocumentError is not None
        assert callable(confirm_purchase_atomic)
        assert callable(revert_purchase_atomic)
        assert callable(delete_purchase_fully)
        assert callable(delete_sale_fully)

    def test_document_error_raises(self):
        from app.services.document_service import DocumentError
        with pytest.raises(DocumentError) as exc_info:
            raise DocumentError("test xato", status_code=400)
        assert exc_info.value.detail == "test xato"
        assert exc_info.value.status_code == 400


class TestAuthHelpers:
    """Tier B3 — Agent PIN helpers."""

    def test_hash_verify_pin(self):
        from app.utils.auth import hash_pin, verify_pin, validate_pin_format
        # Valid PIN
        pin = "5678"
        hashed = hash_pin(pin)
        assert hashed.startswith("$2")  # bcrypt format
        assert verify_pin(pin, hashed) is True
        assert verify_pin("1234", hashed) is False

    def test_pin_format_validation(self):
        from app.utils.auth import validate_pin_format
        # Valid
        assert validate_pin_format("5678") is None
        assert validate_pin_format("246813") is None
        # Too simple
        assert validate_pin_format("1234") is not None
        assert validate_pin_format("0000") is not None
        # Wrong format
        assert validate_pin_format("abcd") is not None
        assert validate_pin_format("12") is not None  # too short
        assert validate_pin_format("123456789") is not None  # too long


class TestRateLimit:
    """Tier B3 — Per-agent rate limit."""

    def test_is_agent_blocked_initial(self):
        from app.utils.rate_limit import is_agent_blocked, record_agent_success
        # Clean state
        record_agent_success("test_key_123")
        blocked, remaining = is_agent_blocked("test_key_123")
        assert blocked is False
        assert remaining == 0

    def test_agent_failure_and_block(self):
        from app.utils.rate_limit import (
            is_agent_blocked, record_agent_failure, record_agent_success,
            AGENT_MAX_ATTEMPTS,
        )
        key = "test_block_key"
        # Clean
        record_agent_success(key)
        # Failures
        for _ in range(AGENT_MAX_ATTEMPTS):
            record_agent_failure(key)
        blocked, remaining = is_agent_blocked(key)
        assert blocked is True
        assert remaining > 0
        # Cleanup
        record_agent_success(key)


class TestLiveBackup:
    """Backup infrastructure — scripts/backup_live.py."""

    def test_backup_script_imports(self):
        import sys
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from backup_live import run_live_backup
        assert callable(run_live_backup)

    def test_restore_script_imports(self):
        import sys
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import restore_from_backup
        assert hasattr(restore_from_backup, "list_backups")


class TestMainAppIntegrity:
    """main.py hamma routerlarni to'g'ri ro'yxatga olganini tekshirish."""

    def test_total_routes(self):
        from main import app
        assert len(app.routes) >= 485, f"Kutilgan >=485, topilgan: {len(app.routes)}"

    def test_all_api_endpoints_present(self):
        from main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        # Key API endpoints
        assert "/api/login" in paths
        assert "/api/stats" in paths
        assert "/api/pwa/config" in paths
        assert "/api/agent/login" in paths
        assert "/api/driver/login" in paths
        assert "/api/notifications/unread" in paths

    def test_all_employees_endpoints_present(self):
        from main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        # All 6 employees sub-modules routes
        assert "/employees" in paths
        assert "/employees/dismissal/create" in paths
        assert "/employees/advances" in paths
        assert "/employees/attendance" in paths
        assert "/employees/salary" in paths
        assert "/employees/hiring-docs" in paths
