"""Z-hisobot uchun naqd kassa hisoboti.

Smena yopilganda yoki ko'rilganda quyidagilarni hisoblaydi:
- naqd savdo (pure + split ichidagi naqd)
- naqd harajat (smena davomida)
- naqd kontragentga to'lov
- naqd kassadan kassaga o'tkazma (inkasatsiya)  ← 2026-05-26 fix
- oldingi Z dan boshlang'ich qoldiq (chain)
- yakuniy qoldiq = oldingi + savdo − harajat − to'lov − inkasatsiya

Sales.py (save) va reports.py (view) dan chaqiriladi.
"""
from __future__ import annotations

import json
import os
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import Order, Payment, CashTransfer, CashRegister, User


def compute_z_cash_summary(db: Session, target_date: date, user_id: int, until_dt=None) -> dict:
    """Naqd kassa hisoboti: smena uchun kirim/chiqim summasini hisoblash.

    Args:
        until_dt: agar berilgan bo'lsa, faqat shu vaqtgacha bo'lgan aktivlik hisoblanadi
                  (Order/Payment.created_at <= until_dt). Sales.py'da Z yopilgan moment uzatiladi.
                  None = butun kun (eski Z snapshotlar uchun retroaktiv to'ldirishda).

    Returns:
        cash_sales_pure       — bir to'lov kanali bo'lgan buyurtmalardagi naqd
        cash_sales_split      — bir nechta to'lov kanali bo'lgan buyurtmalardagi naqd qismi
        cash_sales_total      — pure + split
        cash_expenses_total   — naqd harajatlar (kassadan har qanday chiqim)
        cash_payments_out     — naqd kontragentga to'lov (supplier_payment)
        cash_transfers_out    — naqd kassadan kassaga o'tkazma (inkasatsiya)  ← 2026-05-26 fix
    """
    from sqlalchemy import distinct, select
    from sqlalchemy.orm import joinedload

    order_where = [
        func.date(Order.created_at) == target_date,
        Order.user_id == user_id,
        Order.status.in_(("completed", "delivered")),
    ]
    if until_dt is not None:
        order_where.append(Order.created_at <= until_dt)
    sale_ids_select = select(Order.id).where(*order_where)

    confirmed = (Payment.status == "confirmed")
    naqd_types = ("cash", "naqd")

    # Split = bir Order ichida bir nechta payment_type (Order.payment_type='split' ga ishonib bo'lmaydi —
    # POS uni hamma uchun yozadi). Confirmed Payment'lar bo'yicha aniqlanadi.
    split_order_ids_select = (
        select(Payment.order_id)
        .where(Payment.order_id.in_(sale_ids_select), confirmed)
        .group_by(Payment.order_id)
        .having(func.count(distinct(Payment.payment_type)) > 1)
    )

    pay_in_filters = [
        Payment.payment_type.in_(naqd_types),
        Payment.type == "income",
        confirmed,
        Payment.order_id.in_(sale_ids_select),
    ]
    if until_dt is not None:
        pay_in_filters.append(Payment.created_at <= until_dt)

    cash_sales_total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(*pay_in_filters).scalar() or 0.0
    cash_sales_split = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        *(pay_in_filters[:3] + [Payment.order_id.in_(split_order_ids_select)] +
          ([Payment.created_at <= until_dt] if until_dt is not None else []))
    ).scalar() or 0.0
    cash_sales_pure = float(cash_sales_total) - float(cash_sales_split)

    exp_filters = [
        func.date(Payment.created_at) == target_date,
        Payment.user_id == user_id,
        Payment.type == "expense",
        Payment.payment_type.in_(naqd_types),
        confirmed,
    ]
    if until_dt is not None:
        exp_filters.append(Payment.created_at <= until_dt)

    cash_expenses_total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        *exp_filters, Payment.category.in_(("expense", "expense_doc", "other")),
    ).scalar() or 0.0

    cash_payments_out = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        *exp_filters, Payment.category == "supplier_payment",
    ).scalar() or 0.0

    # === 2026-05-26 fix: CashTransfer (kassadan kassaga) hisobga olish ===
    # Foydalanuvchining naqd POS kassalaridan chiqayotgan o'tkazmalar (inkasatsiya).
    # X-hisobotda allaqachon inkasatsiya_naqd_today sifatida hisoblanadi (sales.py:2269-2274).
    # Z-hisobot ham shu mantiqni qaytarmasa, naqd qoldiq xayoliy ko'p chiqadi.
    cash_transfers_out = 0.0
    try:
        user_full = db.query(User).options(joinedload(User.cash_registers_list)).filter(User.id == user_id).first()
        user_cashes = list(getattr(user_full, "cash_registers_list", None) or []) if user_full else []
        naqd_cash_ids = [
            c.id for c in user_cashes
            if (c.payment_type or "").strip().lower() == "naqd"
        ]
        if naqd_cash_ids:
            tr_filters = [
                CashTransfer.from_cash_id.in_(naqd_cash_ids),
                CashTransfer.status.in_(("in_transit", "completed")),
                func.date(CashTransfer.date) == target_date,
            ]
            if until_dt is not None:
                tr_filters.append(CashTransfer.date <= until_dt)
            cash_transfers_out = db.query(
                func.coalesce(func.sum(CashTransfer.amount), 0)
            ).filter(*tr_filters).scalar() or 0.0
    except Exception:
        # Defensive: schema drift yoki user_id'siz holatda 0 qaytaring.
        cash_transfers_out = 0.0

    return {
        "cash_sales_pure": float(cash_sales_pure),
        "cash_sales_split": float(cash_sales_split),
        "cash_sales_total": float(cash_sales_total),
        "cash_expenses_total": float(cash_expenses_total),
        "cash_payments_out": float(cash_payments_out),
        "cash_transfers_out": float(cash_transfers_out),
    }


def find_previous_z_remaining(
    user_id: int,
    warehouse_id,
    before_closed_at: str,
    z_reports_dir: str = "data/z_reports",
) -> tuple[float, str | None]:
    """Oldingi kunlardagi Z-snapshot dan cash_remaining ni topadi.

    Filter: shu user_id + shu warehouse_id + snap.date < before_closed_at sanasi.
    Bir kun ichidagi avvalgi Z'lar HISOBGA OLINMAYDI — ular bilan chain double-count
    qiladi (compute_z_cash_summary butun kun sotuvni qaytaradi). Foydalanuvchi
    formulasi: "keyingi kunda avvalgi Z farqi qo'shiladi".

    Returns:
        (cash_remaining, z_id) — topilmasa (0.0, None)
    """
    if not os.path.isdir(z_reports_dir):
        return (0.0, None)

    target_date_str = (before_closed_at or "")[:10]  # 'YYYY-MM-DD'

    best_ts = ""
    best_remaining = 0.0
    best_zid: str | None = None

    try:
        folders = sorted(os.listdir(z_reports_dir), reverse=True)
    except OSError:
        return (0.0, None)

    for folder in folders[:60]:
        # Bugungi (yoki kelajak) papkalarni o'tkazib yuborish
        if target_date_str and folder >= target_date_str:
            continue
        folder_path = os.path.join(z_reports_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        try:
            files = os.listdir(folder_path)
        except OSError:
            continue
        for fname in files:
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder_path, fname), "r", encoding="utf-8") as f:
                    snap = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if int(snap.get("user_id") or 0) != int(user_id):
                continue
            if snap.get("warehouse_id") != warehouse_id:
                continue
            closed_at = snap.get("closed_at") or ""
            if not closed_at:
                continue
            snap_date = (snap.get("date") or closed_at)[:10]
            if target_date_str and snap_date >= target_date_str:
                continue
            if closed_at > best_ts:
                best_ts = closed_at
                best_remaining = float(snap.get("cash_remaining") or 0)
                best_zid = snap.get("z_id")
        if best_ts:
            break

    return (best_remaining, best_zid)
