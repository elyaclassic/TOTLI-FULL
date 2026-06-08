"""MEDIUM M1 + M2 + M3 fix testlari (payment FK bog'lash + order-debt recompute).

M1: avans bekor qilish FK (advance.payment_id) orqali aniq Payment'ni topadi —
    fuzzy-match (ism+summa+sana) noto'g'ri Payment'ni o'chirardi.
M3: agent payment revert/delete FK (agent_payment.payment_id) orqali — category-match
    BARCHA bir xil summali to'lovni o'chirardi.
M2: recompute_partner_order_debts per-order paid/debt'ni to'lovlardan qayta-derive.
"""
from datetime import datetime, date


# ============ M1 ============

def test_m1_ensure_sets_payment_id(db):
    from app.models.database import Employee, CashRegister, EmployeeAdvance, Payment
    from app.routes.employees_advances import _ensure_advance_payment

    emp = Employee(full_name="Akmal")
    cr = CashRegister(name="K", payment_type="naqd", is_active=True)
    db.add_all([emp, cr]); db.flush()
    adv = EmployeeAdvance(employee_id=emp.id, cash_register_id=cr.id, amount=500000,
                          advance_date=date(2026, 6, 1), confirmed_at=datetime.now())
    db.add(adv); db.flush()

    class _U:
        id = 1
    _ensure_advance_payment(db, adv, _U())
    db.flush()
    assert adv.payment_id is not None, "Avans Payment'ga FK bilan bog'lanishi kerak"
    pay = db.query(Payment).filter(Payment.id == adv.payment_id).first()
    assert pay and pay.type == "expense" and float(pay.amount) == 500000


def test_m1_cancel_uses_fk_not_fuzzy(db):
    """2 ta bir xil emp/summa/sana avans, har biri alohida Payment. Bittasini bekor
    qilganda FK orqali AYNAN o'sha Payment bekor bo'ladi (fuzzy id.desc() boshqasini olardi)."""
    from app.models.database import Employee, CashRegister, EmployeeAdvance, Payment
    from app.routes.employees_advances import _cancel_linked_advance_payment

    emp = Employee(full_name="Akmal")
    cr = CashRegister(name="K", payment_type="naqd", is_active=True)
    db.add_all([emp, cr]); db.flush()
    adv1 = EmployeeAdvance(employee_id=emp.id, cash_register_id=cr.id, amount=500000,
                           advance_date=date(2026, 6, 1), confirmed_at=datetime.now())
    adv2 = EmployeeAdvance(employee_id=emp.id, cash_register_id=cr.id, amount=500000,
                           advance_date=date(2026, 6, 1), confirmed_at=datetime.now())
    db.add_all([adv1, adv2]); db.flush()
    # Har avans uchun alohida (lekin bir xil tafsilotli) Payment + FK
    common = dict(date=datetime(2026, 6, 1, 10), type="expense", cash_register_id=cr.id,
                  amount=500000, status="confirmed", description="Avans: Akmal", category="other")
    pay1 = Payment(number="PAY-M1-1", **common)
    pay2 = Payment(number="PAY-M1-2", **common)
    db.add_all([pay1, pay2]); db.flush()
    adv1.payment_id = pay1.id
    adv2.payment_id = pay2.id
    db.flush()

    _cancel_linked_advance_payment(db, adv1)
    db.flush()
    assert db.query(Payment).filter(Payment.id == pay1.id).first().status == "cancelled"
    assert db.query(Payment).filter(Payment.id == pay2.id).first().status == "confirmed", \
        "Boshqa avansning Payment'i tegilmasligi kerak (FK aniqligi)"


# ============ M3 ============

def test_m3_delete_uses_fk_not_category(db):
    """2 ta bir xil partner+summa agent_collection Payment. AgentPayment FK orqali faqat
    o'zinikini o'chiradi (category-match ikkalasini ham o'chirardi)."""
    from app.models.database import AgentPayment, Payment, Partner
    from app.routes.delivery_routes import _delete_linked_agent_payment

    p = Partner(name="Mijoz", balance=0, code="P_M3")
    db.add(p); db.flush()
    pay1 = Payment(number="AGT-M3-1", date=datetime.now(), type="income", amount=300000,
                   partner_id=p.id, category="agent_collection", status="confirmed")
    pay2 = Payment(number="AGT-M3-2", date=datetime.now(), type="income", amount=300000,
                   partner_id=p.id, category="agent_collection", status="confirmed")
    db.add_all([pay1, pay2]); db.flush()
    ap1 = AgentPayment(partner_id=p.id, amount=300000, status="confirmed", payment_id=pay1.id)
    db.add(ap1); db.flush()

    deleted = _delete_linked_agent_payment(db, ap1)
    db.flush()
    assert deleted == 1
    assert db.query(Payment).filter(Payment.id == pay1.id).first() is None, "O'zining Payment'i o'chadi"
    assert db.query(Payment).filter(Payment.id == pay2.id).first() is not None, \
        "Boshqa bir xil summali Payment tegilmasligi kerak (FK aniqligi)"


def test_m3_delete_fallback_category_when_no_fk(db):
    """FK NULL (eski yozuv) bo'lsa category-match fallback ishlaydi."""
    from app.models.database import AgentPayment, Payment, Partner
    from app.routes.delivery_routes import _delete_linked_agent_payment

    p = Partner(name="Mijoz2", balance=0, code="P_M3b")
    db.add(p); db.flush()
    pay = Payment(number="AGT-M3-3", date=datetime.now(), type="income", amount=150000,
                  partner_id=p.id, category="agent_collection", status="confirmed")
    db.add(pay); db.flush()
    ap = AgentPayment(partner_id=p.id, amount=150000, status="confirmed", payment_id=None)
    db.add(ap); db.flush()

    deleted = _delete_linked_agent_payment(db, ap)
    db.flush()
    assert deleted == 1
    assert db.query(Payment).filter(Payment.id == pay.id).first() is None


# ============ M2 ============

def test_m2_recompute_order_debts_linked_and_fifo(db):
    """order_id'li to'lov o'z orderiga, ortiqcha FIFO eng eskiga."""
    from app.models.database import Order, Payment, Partner
    from app.services.partner_balance_service import recompute_partner_order_debts

    p = Partner(name="P", balance=0, code="P_M2")
    db.add(p); db.flush()
    # 2 sale order: o1 (eski, 100k), o2 (yangi, 60k) — paid/debt ataylab noto'g'ri
    o1 = Order(number="S-M2-1", date=datetime(2026, 6, 1), type="sale", partner_id=p.id,
               total=100000, paid=0, debt=100000, status="delivered")
    o2 = Order(number="S-M2-2", date=datetime(2026, 6, 2), type="sale", partner_id=p.id,
               total=60000, paid=60000, debt=0, status="delivered")  # noto'g'ri: drift
    db.add_all([o1, o2]); db.flush()
    # 120k to'lov, o1 ga bog'langan (order_id=o1) — 100k o1 ga, 20k ortiqcha FIFO -> o2
    pay = Payment(number="PAY-M2-1", date=datetime.now(), type="income", amount=120000,
                  partner_id=p.id, order_id=o1.id, status="confirmed")
    db.add(pay); db.flush()

    changed = recompute_partner_order_debts(db, p.id)
    db.flush()
    db.refresh(o1); db.refresh(o2)
    assert float(o1.paid) == 100000 and float(o1.debt) == 0, f"o1: paid={o1.paid} debt={o1.debt}"
    assert float(o2.paid) == 20000 and float(o2.debt) == 40000, f"o2: paid={o2.paid} debt={o2.debt}"
    assert changed >= 1


def test_m2_agent_order_not_eligible_until_delivered(db):
    """Agent order confirmed (yetkazilmagan) hali qarz emas — recompute uni hisobga olmaydi."""
    from app.models.database import Order, Payment, Partner
    from app.services.partner_balance_service import recompute_partner_order_debts

    p = Partner(name="P2", balance=0, code="P_M2b")
    db.add(p); db.flush()
    o = Order(number="AGT-M2-1", date=datetime(2026, 6, 1), type="sale", source="agent",
              partner_id=p.id, total=50000, paid=0, debt=50000, status="confirmed")  # yetkazilmagan
    db.add(o); db.flush()
    pay = Payment(number="PAY-M2-2", date=datetime.now(), type="income", amount=50000,
                  partner_id=p.id, status="confirmed")
    db.add(pay); db.flush()

    recompute_partner_order_debts(db, p.id)
    db.refresh(o)
    # eligible emas -> paid/debt o'zgartirilmaydi
    assert float(o.debt) == 50000, "Yetkazilmagan agent order recompute'dan ta'sirlanmasligi kerak"
