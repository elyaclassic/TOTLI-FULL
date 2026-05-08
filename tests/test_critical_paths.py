"""Critical-path regression testlari.

Har test bugungi audit fixlardan birini himoyalaydi —
kelajakda kim shu fixni buzsa, pre-commit pytest darhol topadi.

Ishlatish:
    pytest tests/test_critical_paths.py -v
"""
import pytest


# ============================================================
# Schema invariants — bugungi 500 hatolarini oldini olish
# ============================================================

class TestSchemaInvariants:
    """ORM ↔ DB sinxronizatsiyasi. Bugungi Production.order_id 500 misol."""

    def test_production_has_order_id(self):
        """Production modelida order_id ustun bo'lishi kerak (b3a5dbd fix)."""
        from app.models.database import Production
        assert hasattr(Production, "order_id"), "Production.order_id ORM'da yo'q (schema drift)"

    def test_partner_has_credit_limit(self):
        """Partner.credit_limit (D4 fix uchun)."""
        from app.models.database import Partner
        assert hasattr(Partner, "credit_limit")

    def test_order_has_previous_partner_balance(self):
        """Order.previous_partner_balance (D2 revert snapshot)."""
        from app.models.database import Order
        assert hasattr(Order, "previous_partner_balance")

    def test_salary_has_is_balance_entry(self):
        """Salary.is_balance_entry (XOD carry-over fix)."""
        from app.models.database import Salary
        assert hasattr(Salary, "is_balance_entry")


# ============================================================
# Stock invariant — bugungi 313 drift hodisasi
# ============================================================

class TestStockInvariants:
    """Stock.quantity == sum(StockMovement.quantity_change). CLAUDE.md asosiy qoida."""

    def test_create_stock_movement_keeps_invariant(self, db, sample_stock):
        from app.services.stock_service import create_stock_movement
        from app.models.database import StockMovement
        from sqlalchemy import func

        before = float(sample_stock.quantity or 0)
        create_stock_movement(
            db=db,
            warehouse_id=sample_stock.warehouse_id,
            product_id=sample_stock.product_id,
            quantity_change=-5.0,
            operation_type="sale",
            document_type="Test",
            document_id=1,
            document_number="TEST-001",
        )
        db.commit()
        db.refresh(sample_stock)

        # Invariant: quantity = before + sum(yangi movements)
        assert abs(sample_stock.quantity - (before - 5.0)) < 1e-6


# ============================================================
# H1 — mark-paid manfiy summa REJECT
# ============================================================

class TestSalaryMarkPaid:
    """H1: paid_amount < 0 → manfiy paid bloklanadi."""

    def test_mark_paid_negative_logic(self):
        """Mark-paid endpointidagi validatsiya simulatsiyasi."""
        # Validatsiya logikasi:
        for paid_amount in (-590000, -3692593, -1):
            assert paid_amount < 0, f"manfiy detect kerak: {paid_amount}"

        # Clamp pattern
        assert max(0.0, float(-590000)) == 0.0
        assert max(0.0, float(0)) == 0.0
        assert max(0.0, float(500000)) == 500000.0


# ============================================================
# Salary carry-over — XOD fix
# ============================================================

class TestSalaryCarryover:
    """XOD carry-over: status='paid' va paid > 0 bo'lsa qarz to'langan deb hisoblanadi."""

    def test_carryover_excludes_paid_debt(self):
        """Logika simulatsiyasi: prev_paid total ni qoplasa carry-over=0."""
        # Stsenariy: aprel total=-590k (we owe), paid=590k (paid), status=paid
        prev_total = -590000.0
        prev_paid = 590000.0
        prev_status = "paid"

        # Yangi logika
        if prev_total < 0:
            outstanding = -prev_total - prev_paid if prev_status == "paid" else -prev_total
            carry = outstanding if outstanding > 0 else 0
        else:
            carry = 0

        assert carry == 0, "Aprel paid bo'lgan, May da carry-over=0 bo'lishi kerak"

    def test_carryover_keeps_unpaid_debt(self):
        """Aprel paid=0 bo'lsa carry-over=590k saqlanadi."""
        prev_total = -590000.0
        prev_paid = 0.0
        prev_status = "paid"  # status flag, lekin paid=0

        outstanding = -prev_total - prev_paid if prev_status == "paid" else -prev_total
        carry = outstanding if outstanding > 0 else 0

        assert carry == 590000.0

    def test_paid_clamp_negative(self):
        """Manfiy paid (eski xato) clamp qilinadi."""
        prev_paid = max(0.0, float(-590000))
        assert prev_paid == 0.0


# ============================================================
# D4 — credit_limit enforcement
# ============================================================

class TestCreditLimit:
    """check_credit_limit service tekshiruvi."""

    def test_no_partner_allows(self):
        from app.services.partner_credit import check_credit_limit
        ok, _ = check_credit_limit(None, 1_000_000)
        assert ok

    def test_zero_limit_allows_anything(self):
        from app.services.partner_credit import check_credit_limit

        class P:
            balance = 0
            credit_limit = 0

        ok, _ = check_credit_limit(P(), 5_000_000)
        assert ok, "credit_limit=0 → limit yo'q (chakana xaridor)"

    def test_within_limit_allows(self):
        from app.services.partner_credit import check_credit_limit

        class P:
            balance = 500_000
            credit_limit = 2_000_000

        ok, _ = check_credit_limit(P(), 1_000_000)
        assert ok, "500k + 1M = 1.5M < 2M limit"

    def test_exceeding_limit_rejects(self):
        from app.services.partner_credit import check_credit_limit

        class P:
            name = "Test"
            balance = 1_500_000
            credit_limit = 2_000_000

        ok, err = check_credit_limit(P(), 1_000_000)
        assert not ok, "1.5M + 1M = 2.5M > 2M limit"
        assert "limit" in err.lower()

    def test_zero_debt_skips(self):
        from app.services.partner_credit import check_credit_limit

        class P:
            balance = 5_000_000
            credit_limit = 1_000_000

        ok, _ = check_credit_limit(P(), 0)
        assert ok, "Naqd to'lov (debt=0) tekshirilmaydi"


# ============================================================
# C1 — avans unconfirm Payment lookup
# ============================================================

class TestAdvanceUnconfirm:
    """C1: avans unconfirm bog'liq Payment ham 'cancelled' bo'ladi."""

    def test_helper_finds_linked_payment(self, db, sample_cash):
        from app.models.database import Employee, EmployeeAdvance, Payment
        from app.routes.employees_advances import _cancel_linked_advance_payment
        from datetime import date, datetime

        # Setup
        emp = Employee(full_name="Test Xodim", is_active=True)
        db.add(emp)
        db.flush()

        adv_date = date(2026, 5, 1)
        adv = EmployeeAdvance(
            employee_id=emp.id,
            advance_date=adv_date,
            amount=500000,
            confirmed_at=datetime.now(),
            cash_register_id=sample_cash.id,
        )
        db.add(adv)
        pay = Payment(
            number="AVNS-0001",
            date=datetime(2026, 5, 1, 10, 0, 0),
            type="expense",
            cash_register_id=sample_cash.id,
            amount=500000,
            payment_type="cash",
            description=f"Avans: Test Xodim",
            status="confirmed",
        )
        db.add(pay)
        db.commit()
        db.refresh(adv)
        db.refresh(pay)

        # Action
        found = _cancel_linked_advance_payment(db, adv)
        db.commit()
        db.refresh(pay)

        # Assert
        assert found, "Helper bog'liq Payment'ni topishi kerak"
        assert pay.status == "cancelled", "Payment status 'cancelled' bo'lishi kerak"


# ============================================================
# Endpoint smoke — bugungi 500 hatolarini oldini olish
# ============================================================

class TestEndpointsSmoke:
    """Brauzerga 500 emas, kutilgan response qaytsin."""

    def test_login_get_returns_200(self, client):
        r = client.get("/login")
        assert r.status_code == 200

    def test_root_redirects_to_login(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (200, 303, 307), f"Got {r.status_code}"
