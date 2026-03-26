"""Barcha hisobot uchun SQL so'rovlar"""
from datetime import date, datetime, timedelta
from calendar import monthrange
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_

from app.models.database import (
    Order, OrderItem, Product, Partner, Payment,
    Attendance, Employee, Salary,
    ExpenseDoc, ExpenseDocItem, ExpenseType,
    CashRegister, Stock, Agent, Production, Recipe,
)
from app.utils.production_order import recipe_kg_per_unit


def parse_period(period: str):
    """Davr nomidan (today, yesterday, ...) start_date, end_date qaytaradi"""
    today = date.today()
    if period == "today":
        return today, today
    elif period == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period == "this_month":
        return today.replace(day=1), today
    elif period == "last_month":
        first = today.replace(day=1)
        last_month_end = first - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end
    return today, today


def fmt(n) -> str:
    """Sonni formatlash: 1234567 -> 1,234,567"""
    if n is None:
        return "0"
    return f"{float(n):,.0f}"


def _dt_start(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _dt_end(d: date) -> datetime:
    return datetime.combine(d, datetime.max.time())


# ============= 1. DAVOMAT =============
def _sync_hikvision_now(db: Session, start: date, end: date):
    """Hikvision dan so'ralganda yangilash"""
    try:
        from app.utils.hikvision import sync_hikvision_attendance
        sync_hikvision_attendance(
            hikvision_host="192.168.1.199",
            hikvision_port=443,
            hikvision_username="admin",
            hikvision_password="Samsung0707",
            start_date=start,
            end_date=end,
            db_session=db,
        )
    except Exception:
        pass


def report_attendance(db: Session, start: date, end: date) -> str:
    # Avval Hikvision dan yangilash
    _sync_hikvision_now(db, start, end)
    total_days = (end - start).days + 1
    is_single_day = (start == end)
    lines = [f"📋 <b>Davomat hisoboti</b>", f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n"]

    if is_single_day:
        # Bitta kun — kelish/ketish vaqti va soatlar ko'rsatiladi
        rows = (
            db.query(
                Employee.full_name,
                func.strftime("%H:%M", Attendance.check_in).label("t_in"),
                func.strftime("%H:%M", Attendance.check_out).label("t_out"),
                Attendance.hours_worked,
                Attendance.status,
            )
            .join(Attendance, Attendance.employee_id == Employee.id)
            .filter(
                Attendance.date == start,
                or_(Attendance.status == "present", Attendance.check_in.isnot(None)),
            )
            .order_by(Attendance.check_in)
            .all()
        )
        if not rows:
            lines.append("Ma'lumot topilmadi.")
            return "\n".join(lines)
        # Jadval ko'rinishida
        lines.append("<pre>")
        lines.append(f"{'Xodim':<22} {'Keldi':>5}  {'Ketdi':>5}  {'Soat':>4}")
        lines.append("─" * 42)
        present = 0
        total_hours = 0
        for r in rows:
            t_in = r.t_in or "  —  "
            # Agar kelish = ketish bo'lsa — hali ketmagan (ishlayapti)
            if r.t_in and r.t_out and r.t_in == r.t_out:
                t_out = "  ...  "
                hours = " ⏳"
            elif r.hours_worked and r.hours_worked > 0:
                t_out = r.t_out or "  —  "
                hours = f"{r.hours_worked:.1f}"
                total_hours += r.hours_worked
            else:
                t_out = r.t_out or "  —  "
                hours = " —"
            name = r.full_name[:22]
            lines.append(f"{name:<22} {t_in:>5}  {t_out:>5} {hours:>4}")
            present += 1
        lines.append("─" * 42)
        lines.append(f"{'Jami soat:':<34} {total_hours:.1f}")
        lines.append("</pre>")
        # Kelmagan xodimlar (faqat hikvision_id bor xodimlar — sotuvchilar hisoblanmaydi)
        present_ids = set()
        for r in rows:
            emp = db.query(Employee).filter(Employee.full_name == r.full_name).first()
            if emp:
                present_ids.add(emp.id)
        all_hik = db.query(Employee).filter(
            Employee.is_active == True,
            Employee.hikvision_id.isnot(None),
            Employee.hikvision_id != "",
        ).all()
        absent_emps = [e for e in all_hik if e.id not in present_ids]
        lines.append(f"\n✅ Kelgan: <b>{present}</b>  |  ❌ Kelmagan: <b>{len(absent_emps)}</b>")
        if absent_emps:
            lines.append("\n<b>Kelmaganlar:</b>")
            for e in absent_emps:
                lines.append(f"  ❌ {e.full_name}")
    else:
        # Bir necha kun — kunlar soni ko'rsatiladi
        rows = (
            db.query(
                Employee.full_name,
                func.count(func.distinct(Attendance.date)).label("days"),
                func.round(func.avg(Attendance.hours_worked), 1).label("avg_hours"),
            )
            .join(Attendance, Attendance.employee_id == Employee.id)
            .filter(
                Attendance.date >= start,
                Attendance.date <= end,
                or_(Attendance.status == "present", Attendance.check_in.isnot(None)),
            )
            .group_by(Employee.id)
            .order_by(func.count(func.distinct(Attendance.date)).desc())
            .all()
        )
        if not rows:
            lines.append("Ma'lumot topilmadi.")
            return "\n".join(lines)
        lines.append("<pre>")
        lines.append(f"{'Xodim':<22} {'Kun':>3}/{total_days}  {'%':>3}  {'~Soat':>5}")
        lines.append("─" * 42)
        for r in rows:
            pct = round(r.days / total_days * 100)
            avg_h = f"{r.avg_hours:.1f}" if r.avg_hours and r.avg_hours > 0 else "  —"
            name = r.full_name[:22]
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            lines.append(f"{name:<22} {r.days:>3}/{total_days}  {pct:>3}%  {avg_h:>5}")
        lines.append("─" * 42)
        lines.append("</pre>")
        lines.append(f"Jami: <b>{len(rows)}</b> ta xodim")
    return "\n".join(lines)


# ============= 2. SAVDO =============
def report_sales(db: Session, start: date, end: date) -> str:
    orders = db.query(Order).filter(
        Order.type == "sale",
        Order.status.in_(["confirmed", "completed"]),
        Order.date >= _dt_start(start),
        Order.date <= _dt_end(end),
    ).all()
    total_sum = sum(o.total or 0 for o in orders)
    total_paid = sum(o.paid or 0 for o in orders)
    total_debt = sum(o.debt or 0 for o in orders)
    lines = [
        f"💰 <b>Savdo hisoboti</b>",
        f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n",
        f"Buyurtmalar: <b>{len(orders)}</b> ta",
        f"Umumiy summa: <b>{fmt(total_sum)}</b> so'm",
        f"To'langan: <b>{fmt(total_paid)}</b> so'm",
        f"Qarz: <b>{fmt(total_debt)}</b> so'm",
    ]
    # Top 5 mijoz
    partner_totals = {}
    for o in orders:
        if o.partner_id:
            p = db.query(Partner).filter(Partner.id == o.partner_id).first()
            name = p.name if p else "Noma'lum"
            partner_totals[name] = partner_totals.get(name, 0) + (o.total or 0)
    if partner_totals:
        lines.append("\n<b>Top 5 mijoz:</b>")
        for i, (name, total) in enumerate(sorted(partner_totals.items(), key=lambda x: -x[1])[:5], 1):
            lines.append(f"{i}. {name} — {fmt(total)} so'm")
    return "\n".join(lines)


# ============= 3. PUL OQIMI =============
def report_cashflow(db: Session, start: date, end: date) -> str:
    payments = db.query(Payment).filter(
        Payment.created_at >= _dt_start(start),
        Payment.created_at <= _dt_end(end),
    ).all()
    income = sum(p.amount or 0 for p in payments if (p.amount or 0) > 0)
    expense = sum(abs(p.amount or 0) for p in payments if (p.amount or 0) < 0)
    # Kassalar bo'yicha
    kassa_data = {}
    for p in payments:
        k_id = getattr(p, "cash_register_id", None)
        if k_id:
            kassa = db.query(CashRegister).filter(CashRegister.id == k_id).first()
            name = kassa.name if kassa else f"Kassa #{k_id}"
        else:
            name = "Noma'lum"
        if name not in kassa_data:
            kassa_data[name] = {"in": 0, "out": 0}
        if (p.amount or 0) > 0:
            kassa_data[name]["in"] += p.amount
        else:
            kassa_data[name]["out"] += abs(p.amount)
    lines = [
        f"💵 <b>Pul oqimi</b>",
        f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n",
        f"Kirim: <b>{fmt(income)}</b> so'm",
        f"Chiqim: <b>{fmt(expense)}</b> so'm",
        f"Farq: <b>{fmt(income - expense)}</b> so'm",
    ]
    if kassa_data:
        lines.append("\n<b>Kassalar:</b>")
        for name, d in kassa_data.items():
            lines.append(f"  {name}: +{fmt(d['in'])} / -{fmt(d['out'])}")
    return "\n".join(lines)


# ============= 4. HARAJATLAR =============
def report_expenses(db: Session, start: date, end: date) -> str:
    docs = db.query(ExpenseDoc).filter(
        ExpenseDoc.date >= _dt_start(start),
        ExpenseDoc.date <= _dt_end(end),
        ExpenseDoc.status == "confirmed",
    ).all()
    doc_ids = [d.id for d in docs]
    total = 0
    by_type = {}
    if doc_ids:
        items = db.query(ExpenseDocItem).filter(ExpenseDocItem.expense_doc_id.in_(doc_ids)).all()
        for item in items:
            amt = float(item.amount or 0)
            total += amt
            et = db.query(ExpenseType).filter(ExpenseType.id == item.expense_type_id).first() if hasattr(item, "expense_type_id") else None
            name = et.name if et else "Boshqa"
            by_type[name] = by_type.get(name, 0) + amt
    lines = [
        f"📉 <b>Harajatlar hisoboti</b>",
        f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n",
        f"Hujjatlar: <b>{len(docs)}</b> ta",
        f"Jami: <b>{fmt(total)}</b> so'm",
    ]
    if by_type:
        lines.append("\n<b>Turkumlar:</b>")
        for name, amt in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {name}: {fmt(amt)} so'm")
    return "\n".join(lines)


# ============= 5. QARZDORLAR =============
def report_debtors(db: Session, start: date, end: date) -> str:
    # Qarzdorlar: sotuv buyurtmalari qarz > 0
    debtors = (
        db.query(Partner.name, func.sum(Order.debt).label("total_debt"), func.count(Order.id).label("cnt"))
        .join(Partner, Order.partner_id == Partner.id)
        .filter(Order.type == "sale", Order.debt > 0)
        .group_by(Partner.id)
        .order_by(func.sum(Order.debt).desc())
        .all()
    )
    # Haqdorlar: xarid qarz > 0 (biz to'lamaganimiz)
    creditors = (
        db.query(Partner.name, func.sum(Order.debt).label("total_debt"), func.count(Order.id).label("cnt"))
        .join(Partner, Order.partner_id == Partner.id)
        .filter(Order.type == "purchase", Order.debt > 0)
        .group_by(Partner.id)
        .order_by(func.sum(Order.debt).desc())
        .all()
    )
    lines = [f"📌 <b>Qarzdor va haqdorlar</b>\n"]
    total_debtor = sum(r.total_debt or 0 for r in debtors)
    lines.append(f"<b>Qarzdorlar (bizga to'lashi kerak):</b> {fmt(total_debtor)} so'm")
    for i, r in enumerate(debtors[:10], 1):
        lines.append(f"  {i}. {r.name} — {fmt(r.total_debt)} ({r.cnt} ta)")
    if len(debtors) > 10:
        lines.append(f"  ... va yana {len(debtors) - 10} ta")
    total_creditor = sum(r.total_debt or 0 for r in creditors)
    lines.append(f"\n<b>Haqdorlar (biz to'lashimiz kerak):</b> {fmt(total_creditor)} so'm")
    for i, r in enumerate(creditors[:10], 1):
        lines.append(f"  {i}. {r.name} — {fmt(r.total_debt)} ({r.cnt} ta)")
    if len(creditors) > 10:
        lines.append(f"  ... va yana {len(creditors) - 10} ta")
    return "\n".join(lines)


# ============= 6. ISH HAQI =============
def report_salaries(db: Session, start: date, end: date) -> str:
    year = end.year
    month = end.month
    rows = (
        db.query(Employee.full_name, Salary.base_salary, Salary.total, Salary.paid, Salary.status)
        .join(Salary, Salary.employee_id == Employee.id)
        .filter(Salary.year == year, Salary.month == month, Employee.is_active == True)
        .order_by(Employee.full_name)
        .all()
    )
    total_sum = sum(r.total or 0 for r in rows)
    total_paid = sum(r.paid or 0 for r in rows)
    lines = [
        f"💳 <b>Ish haqi — {year}-yil {month}-oy</b>\n",
        f"Xodimlar: <b>{len(rows)}</b> ta",
        f"Jami hisoblangan: <b>{fmt(total_sum)}</b> so'm",
        f"To'langan: <b>{fmt(total_paid)}</b> so'm",
        f"Qoldiq: <b>{fmt(total_sum - total_paid)}</b> so'm\n",
    ]
    for r in rows:
        status_icon = "✅" if r.status == "paid" else "⏳"
        lines.append(f"{status_icon} {r.full_name}: {fmt(r.total)} so'm")
    return "\n".join(lines)


# ============= 7. XODIMLAR KPI =============
def report_kpi(db: Session, start: date, end: date) -> str:
    total_days = (end - start).days + 1
    emps = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    lines = [f"📊 <b>Xodimlar KPI</b>", f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n"]
    for emp in emps:
        att_days = db.query(func.count(func.distinct(Attendance.date))).filter(
            Attendance.employee_id == emp.id,
            Attendance.date >= start,
            Attendance.date <= end,
            or_(Attendance.status == "present", Attendance.check_in.isnot(None)),
        ).scalar() or 0
        avg_hours = db.query(func.avg(Attendance.hours_worked)).filter(
            Attendance.employee_id == emp.id,
            Attendance.date >= start,
            Attendance.date <= end,
            Attendance.hours_worked > 0,
        ).scalar() or 0
        att_pct = round(att_days / total_days * 100) if total_days > 0 else 0
        lines.append(f"{'🟢' if att_pct >= 80 else '🟡' if att_pct >= 50 else '🔴'} {emp.full_name}: {att_days}/{total_days} kun ({att_pct}%), ~{avg_hours:.1f} soat")
    return "\n".join(lines)


# ============= 8. TOP MAHSULOTLAR =============
def report_top_products(db: Session, start: date, end: date) -> str:
    rows = (
        db.query(Product.name, func.sum(OrderItem.quantity).label("qty"), func.sum(OrderItem.total).label("revenue"))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.type == "sale", Order.status.in_(["confirmed", "completed"]), Order.date >= _dt_start(start), Order.date <= _dt_end(end))
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.total).desc())
        .all()
    )
    lines = [f"🏆 <b>Mahsulotlar hisoboti</b>", f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n"]
    if not rows:
        lines.append("Ma'lumot topilmadi.")
        return "\n".join(lines)
    lines.append(f"<b>Eng ko'p sotilgan (Top 10):</b>")
    for i, r in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {r.name} — {fmt(r.qty)} dona, {fmt(r.revenue)} so'm")
    if len(rows) > 3:
        lines.append(f"\n<b>Eng kam sotilgan:</b>")
        for i, r in enumerate(rows[-3:], 1):
            lines.append(f"  {i}. {r.name} — {fmt(r.qty)} dona, {fmt(r.revenue)} so'm")
    return "\n".join(lines)


# ============= 9. AGENTLAR =============
def report_agents(db: Session, start: date, end: date) -> str:
    rows = (
        db.query(Agent.full_name.label("name"), func.count(Order.id).label("cnt"), func.sum(Order.total).label("total"), func.sum(Order.debt).label("debt"))
        .join(Order, Order.agent_id == Agent.id)
        .filter(Order.type == "sale", Order.date >= _dt_start(start), Order.date <= _dt_end(end))
        .group_by(Agent.id)
        .order_by(func.sum(Order.total).desc())
        .all()
    )
    lines = [f"🚗 <b>Agentlar buyurtmalari</b>", f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n"]
    if not rows:
        lines.append("Ma'lumot topilmadi.")
        return "\n".join(lines)
    total_all = sum(r.total or 0 for r in rows)
    total_cnt = sum(r.cnt or 0 for r in rows)
    lines.append(f"Jami: {total_cnt} ta buyurtma, {fmt(total_all)} so'm\n")
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r.name}: {r.cnt} ta, {fmt(r.total)} so'm (qarz: {fmt(r.debt)})")
    return "\n".join(lines)


# ============= 10. ISHLAB CHIQARISH =============
def report_production(db: Session, start: date, end: date) -> str:
    prods = db.query(Production).filter(
        Production.status == "completed",
        Production.date >= _dt_start(start),
        Production.date <= _dt_end(end),
    ).all()
    total_tayyor_kg = 0.0
    total_yarim_kg = 0.0
    total_count = len(prods)
    by_product = {}
    for pr in prods:
        recipe = db.query(Recipe).filter(Recipe.id == pr.recipe_id).first()
        product = db.query(Product).filter(Product.id == recipe.product_id).first() if recipe else None
        p_name = product.name if product else "Noma'lum"
        p_type = getattr(product, "type", "") or ""
        is_qiyom = recipe and "qiyom" in (recipe.name or "").lower()
        if p_type == "yarim_tayyor":
            if not is_qiyom:
                total_yarim_kg += float(pr.quantity or 0)
        else:
            kg = recipe_kg_per_unit(recipe) * float(pr.quantity or 0)
            total_tayyor_kg += kg
        if p_name not in by_product:
            by_product[p_name] = {"qty": 0, "count": 0, "type": p_type}
        by_product[p_name]["qty"] += float(pr.quantity or 0)
        by_product[p_name]["count"] += 1
    lines = [
        f"🏭 <b>Ishlab chiqarish hisoboti</b>",
        f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n",
        f"Buyurtmalar: <b>{total_count}</b> ta",
        f"Tayyor mahsulot: <b>{fmt(total_tayyor_kg)}</b> kg",
        f"Yarim tayyor: <b>{fmt(total_yarim_kg)}</b> kg",
    ]
    # Top mahsulotlar
    sorted_products = sorted(by_product.items(), key=lambda x: -x[1]["qty"])
    if sorted_products:
        lines.append(f"\n<b>Mahsulotlar:</b>")
        for i, (name, d) in enumerate(sorted_products[:15], 1):
            t = "🔶" if d["type"] == "yarim_tayyor" else "✅"
            lines.append(f"  {t} {name}: {fmt(d['qty'])} ({d['count']} ta)")
    return "\n".join(lines)


# ============= 11. OBMEN / VOZVRAT =============
def report_returns(db: Session, start: date, end: date) -> str:
    returns = db.query(Order).filter(
        Order.type.in_(["return_sale", "return_purchase", "return"]),
        Order.date >= _dt_start(start),
        Order.date <= _dt_end(end),
    ).all()
    # Sotuv ichidagi vozvratlar ham bo'lishi mumkin
    if not returns:
        # status bo'yicha ham tekshirish
        returns = db.query(Order).filter(
            Order.status == "returned",
            Order.date >= _dt_start(start),
            Order.date <= _dt_end(end),
        ).all()
    total_sum = sum(o.total or 0 for o in returns)
    lines = [
        f"🔄 <b>Obmen va vozvratlar</b>",
        f"📅 {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n",
        f"Jami: <b>{len(returns)}</b> ta",
        f"Summa: <b>{fmt(total_sum)}</b> so'm",
    ]
    if returns:
        lines.append("")
        for i, o in enumerate(returns[:15], 1):
            p = db.query(Partner).filter(Partner.id == o.partner_id).first() if o.partner_id else None
            p_name = p.name if p else "—"
            lines.append(f"{i}. {o.number or '—'} | {p_name} | {fmt(o.total)} so'm")
    return "\n".join(lines)
