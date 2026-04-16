"""
Audit Watchdog — har operatsiyani avtomatik tahlil qilib, shubhali holatlarni
@elya_classic (REALTIME_CHAT_IDS) ga Telegram orqali xabar beradi.

Ikki rejim:
  1) Real-time: routelar ichidan chaqiriladi (audit_sale, audit_expense, ...).
  2) Digest: scheduler har 30 daqiqada audit_digest() ni chaqiradi — umumiy holat
     (manfiy stock, orphan to'lov, uzoq draft, manfiy kassa). Dedup bor:
     xuddi shu natija 2-marta yuborilmaydi.

Sozlamalar — pastdagi konstantalar.

Barcha funksiyalar try/except bilan o'ralgan — audit hech qachon asosiy
operatsiyani to'xtatmasligi kerak. Cooldown: bitta anomaliya 1 soat ichida
faqat 1 marta yuboriladi (AUDIT_COOLDOWN_MIN).
"""
from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.bot.config import REALTIME_CHAT_IDS
from app.bot.services.notifier import _send_to_chats_sync
from app.bot.services.report_queries import fmt
from app.models.database import (
    SessionLocal,
    Order, OrderItem, Partner, Product, ProductPrice, Stock,
    Production, Recipe, RecipeItem, ProductionItem,
    ExpenseDoc, ExpenseDocItem, Payment, CashRegister, CashTransfer,
    Purchase, PurchaseItem,
    StockAdjustmentDoc,
    Warehouse, WarehouseTransfer, WarehouseTransferItem,
    ProductConversion,
    Delivery,
    User,
)

# ============ GLOBAL SOZLAMALAR ============
def _env_flag(name: str, default: bool = True) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


AUDIT_ENABLED = _env_flag("AUDIT_ENABLED", True)       # False qilsa — hech narsa yuborilmaydi
AUDIT_NOTIFY_ALL = _env_flag("AUDIT_NOTIFY_ALL", True) # Har hodisa uchun activity pulse
ACTIVITY_FLUSH_LIMIT = 60                              # Bitta pulse da max qator

# Miqdor chegaralari (so'm)
BIG_SALE_DEBT = 5_000_000            # Bir buyurtmada qarz
BIG_EXPENSE = 3_000_000              # Bir harajat hujjati
BIG_PAYMENT = 10_000_000             # Bir to'lov
BIG_PURCHASE = 20_000_000            # Bir xarid
HUGE_PARTNER_DEBT = 15_000_000       # Mijoz jami qarzi ogohlantirish
HUGE_DAILY_EXPENSE = 20_000_000      # Bugungi umumiy harajat

# Nisbat chegaralari
COST_TOLERANCE = 0.05                # Tannarxdan 5% past — normal (yaxlitlash)
DISCOUNT_WARN_RATIO = 0.70           # Narx turining 70% dan pastga tushsa
PRICE_DRIFT_RATIO = 0.30             # Xarid narxi ±30% o'zgarsa
RECIPE_DRIFT_RATIO = 0.30            # Retseptdan sarf ±30% farq
STOCK_ADJUST_DELTA = 10              # Inventar qatorda 10+ birlik farq

# Vaqt
STALE_DRAFT_HOURS = 12               # Draft hujjatlar maksimal yoshi
AUDIT_COOLDOWN_MIN = 60              # Bir xil xabar 1 soat ichida 1 marta

# Epsilon (float noise) — bundan kichik qiymatlar e'tiborsiz
NEG_STOCK_EPSILON = 0.01             # Qoldiq -0.01 dan past bo'lsa manfiy deb belgilanadi


def _is_enabled() -> bool:
    return bool(AUDIT_ENABLED)


# ============ COOLDOWN & DEDUP ============
# B5 (O5): Cooldown DB'da saqlanadi — process restart da ham tiklanadi.
# Fallback: DB xatosi bo'lsa in-memory ishlatamiz (audit hech qachon crash qilmasligi kerak).
_cooldown_fallback: Dict[str, datetime] = {}  # DB ishlamasa
_last_digest_sig: Optional[str] = None

# ============ ACTIVITY PULSE (har 10 daqiqa) ============
# @elya_classic uchun "hamma hodisalar" oqimi — shubhasiz amallar ham tushadi.
# Buffer har 10 daqiqada yoki 60 qator to'lganda Telegram ga yuboriladi.
_activity_buffer: List[str] = []
_activity_lock = threading.Lock()


def _log_activity(event_type: str, summary: str):
    """Hodisani activity bufferga qo'shish (shubhasiz amal).
    Hodisalar har 10 daqiqada bir bundle qilib yuboriladi (audit_activity_flush)."""
    if not AUDIT_ENABLED or not AUDIT_NOTIFY_ALL:
        return
    line = f"<i>{datetime.now().strftime('%H:%M')}</i> {event_type} — {summary}"
    with _activity_lock:
        _activity_buffer.append(line)
        # Agar buffer 120 ga yetsa — eng eski 60 ni tashlab yuboramiz (memory safety)
        if len(_activity_buffer) > 120:
            del _activity_buffer[:60]


def _cooldown_ok(key: str) -> bool:
    """True qaytaradi — agar shu key oxirgi AUDIT_COOLDOWN_MIN daqiqada yuborilmagan bo'lsa.
    DB asosli (audit_cooldowns jadvali). DB xato bo'lsa — in-memory fallback."""
    from sqlalchemy import text as _sqlt
    now = datetime.now()
    cutoff = now - timedelta(minutes=AUDIT_COOLDOWN_MIN)

    db = None
    try:
        db = SessionLocal()
        # Joriy holatni tekshirish
        row = db.execute(
            _sqlt("SELECT last_sent_at FROM audit_cooldowns WHERE key = :k"),
            {"k": key},
        ).fetchone()
        if row:
            last_sent = row[0]
            if isinstance(last_sent, str):
                try:
                    last_sent = datetime.fromisoformat(last_sent)
                except Exception:
                    last_sent = None
            if last_sent and last_sent > cutoff:
                return False
            # Yangilash
            db.execute(
                _sqlt("UPDATE audit_cooldowns SET last_sent_at = :t WHERE key = :k"),
                {"t": now, "k": key},
            )
        else:
            db.execute(
                _sqlt("INSERT INTO audit_cooldowns (key, last_sent_at) VALUES (:k, :t)"),
                {"k": key, "t": now},
            )
        db.commit()
        # Eski yozuvlarni tozalash (har 100-chaqiruvda bir marta)
        try:
            import random
            if random.randint(1, 100) == 1:
                db.execute(
                    _sqlt("DELETE FROM audit_cooldowns WHERE last_sent_at < :t"),
                    {"t": now - timedelta(minutes=AUDIT_COOLDOWN_MIN * 3)},
                )
                db.commit()
        except Exception:
            db.rollback()
        return True
    except Exception as e:
        # DB xatosi — in-memory fallback
        try:
            if db:
                db.rollback()
        except Exception:
            pass
        print(f"[Audit cooldown DB fallback] {e}", flush=True)
        last = _cooldown_fallback.get(key)
        if last and (now - last) < timedelta(minutes=AUDIT_COOLDOWN_MIN):
            return False
        _cooldown_fallback[key] = now
        if len(_cooldown_fallback) > 200:
            _cooldown_fallback.clear()
        return True
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass


def _push(text: str, dedup_key: Optional[str] = None):
    """Audit xabarini @elya_classic ga yuborish (xavfsiz, dedup bilan)."""
    if not _is_enabled():
        return
    if dedup_key and not _cooldown_ok(dedup_key):
        return
    try:
        _send_to_chats_sync(text, REALTIME_CHAT_IDS)
    except Exception as e:
        print(f"[Audit] TG push xato: {e}", flush=True)


def _hdr(level: str, title: str) -> str:
    icon = {"ok": "✅", "info": "ℹ️", "warn": "⚠️", "alert": "🚨"}.get(level, "•")
    return f"{icon} <b>AUDIT — {title}</b>\n"


def _fmt_list(lines: List[str], max_n: int = 8) -> str:
    out = "\n".join(lines[:max_n])
    if len(lines) > max_n:
        out += f"\n... va yana {len(lines) - max_n} ta"
    return out


def _expected_sale_price(db: Session, product_id: int, price_type_id: Optional[int]) -> float:
    """Mijoz narx turi bo'yicha sotuv narxini qaytaradi. Agar yo'q bo'lsa —
    Product.sale_price (default)."""
    if price_type_id:
        pp = db.query(ProductPrice).filter(
            ProductPrice.product_id == product_id,
            ProductPrice.price_type_id == price_type_id,
        ).first()
        if pp and (pp.sale_price or 0) > 0:
            return float(pp.sale_price or 0)
    p = db.query(Product).filter(Product.id == product_id).first()
    return float(p.sale_price or 0) if p else 0.0


# ============ 1) SOTUV ============
def audit_sale(order_id: int):
    """Sotuv tasdiqlangandan keyin chaqiriladi.
    Tekshiradi: bo'sh sotuv, tannarxdan past, katta chegirma, katta qarz,
    mijoz jami qarzi yuqori."""
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
        if not o:
            return
        warnings: List[str] = []
        items = db.query(OrderItem).filter(OrderItem.order_id == o.id).all()

        if not items:
            warnings.append("• Qatorlar yo'q (bo'sh sotuv)")

        for it in items:
            p = db.query(Product).filter(Product.id == it.product_id).first()
            if not p:
                continue
            unit_price = float(it.price or 0)
            cost = float(p.purchase_price or 0)
            expected = _expected_sale_price(db, p.id, o.price_type_id)

            # Zarar — tannarxdan past (5% rounding tolerance)
            if cost > 0 and unit_price > 0 and unit_price < cost * (1 - COST_TOLERANCE):
                warnings.append(
                    f"• <b>{p.name}</b>: <b>{fmt(unit_price)}</b> &lt; tannarx {fmt(cost)} (ZARAR)"
                )
            # Katta chegirma — mos narx turidan 30%+ past
            elif expected > 0 and unit_price > 0 and unit_price < expected * DISCOUNT_WARN_RATIO:
                pct = int((1 - unit_price / expected) * 100)
                warnings.append(
                    f"• <b>{p.name}</b>: {fmt(unit_price)} ({pct}% chegirma, narx turi: {fmt(expected)})"
                )

        debt = float(o.debt or 0)
        total = float(o.total or 0)
        if debt >= BIG_SALE_DEBT:
            warnings.append(f"• Katta qarz: <b>{fmt(debt)}</b> so'm")

        # Mijoz jami qarzi
        partner = None
        if o.partner_id:
            partner = db.query(Partner).filter(Partner.id == o.partner_id).first()
            if partner and (partner.balance or 0) >= HUGE_PARTNER_DEBT:
                warnings.append(f"• Mijoz <b>{partner.name}</b> jami qarzi: <b>{fmt(partner.balance)}</b>")

        if warnings:
            p_name = partner.name if partner else "Naqd"
            text = (
                _hdr("warn", "Sotuv shubhali")
                + f"\nHujjat: <b>{o.number}</b>\nMijoz: {p_name}\n"
                + f"Summa: {fmt(total)}, qarz: {fmt(debt)}\n\n"
                + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"sale:{o.id}")
        else:
            p_name = partner.name if partner else "Naqd"
            _log_activity(
                "🛒 SOTUV",
                f"<b>{o.number}</b>: {p_name} — {fmt(total)} so'm" + (f" (qarz: {fmt(debt)})" if debt > 0 else ""),
            )
    except Exception as e:
        print(f"[Audit] sale xato: {e}", flush=True)
    finally:
        db.close()


# ============ 2) XARID ============
def audit_purchase(purchase_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        pu = db.query(Purchase).filter(Purchase.id == purchase_id).first()
        if not pu:
            return
        warnings: List[str] = []
        items = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pu.id).all()

        if not items:
            warnings.append("• Qatorlar yo'q")

        for it in items:
            p = db.query(Product).filter(Product.id == it.product_id).first()
            if not p:
                continue
            unit = float(it.price or 0)
            old = float(p.purchase_price or 0)
            # Drift — faqat oldingi narx ma'lum bo'lsa (100+ so'm)
            if old >= 100 and unit > 0:
                ratio = abs(unit - old) / old
                if ratio >= PRICE_DRIFT_RATIO:
                    sign = "↑" if unit > old else "↓"
                    warnings.append(
                        f"• <b>{p.name}</b>: narx {sign} {int(ratio*100)}% ({fmt(old)} → <b>{fmt(unit)}</b>)"
                    )
            if (it.quantity or 0) <= 0:
                warnings.append(f"• <b>{p.name}</b>: miqdor 0 yoki manfiy")

        total = float(pu.total or 0) + float(pu.total_expenses or 0)
        if total >= BIG_PURCHASE:
            warnings.append(f"• Katta xarid: <b>{fmt(total)}</b> so'm")

        partner = db.query(Partner).filter(Partner.id == pu.partner_id).first() if pu.partner_id else None
        p_name = partner.name if partner else "—"
        if warnings:
            text = (
                _hdr("warn", "Xarid shubhali")
                + f"\nHujjat: <b>{pu.number}</b>\nTa'minotchi: {p_name}\n"
                + f"Summa: {fmt(total)}\n\n" + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"purchase:{pu.id}")
        else:
            _log_activity(
                "📥 XARID",
                f"<b>{pu.number}</b>: {p_name} — {fmt(total)} so'm",
            )
    except Exception as e:
        print(f"[Audit] purchase xato: {e}", flush=True)
    finally:
        db.close()


# ============ 3) ISHLAB CHIQARISH ============
def audit_production(prod_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        pr = db.query(Production).filter(Production.id == prod_id).first()
        if not pr:
            return
        warnings: List[str] = []
        recipe = db.query(Recipe).filter(Recipe.id == pr.recipe_id).first()
        qty = float(pr.quantity or 0)

        if qty <= 0:
            warnings.append("• Miqdor 0 yoki manfiy")
        if not pr.operator_id:
            warnings.append("• Operator belgilanmagan")

        # Retseptdan sarf farqi (faqat production_items mavjud bo'lsa)
        if recipe and qty > 0:
            prod_items = db.query(ProductionItem).filter(ProductionItem.production_id == pr.id).all()
            if prod_items:
                recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
                prod_map = {pi.product_id: float(pi.quantity or 0) for pi in prod_items}
                for ri in recipe_items:
                    expected = float(ri.quantity or 0) * qty
                    if expected <= 0:
                        continue
                    actual = prod_map.get(ri.product_id)
                    if actual is None:
                        continue
                    ratio = abs(actual - expected) / expected
                    if ratio >= RECIPE_DRIFT_RATIO:
                        p = db.query(Product).filter(Product.id == ri.product_id).first()
                        pname = p.name if p else f"#{ri.product_id}"
                        sign = "↑" if actual > expected else "↓"
                        warnings.append(
                            f"• <b>{pname}</b>: retseptdan {sign} {int(ratio*100)}% ({fmt(expected)} → <b>{fmt(actual)}</b>)"
                        )

        p_name = ""
        if recipe:
            prod = db.query(Product).filter(Product.id == recipe.product_id).first()
            p_name = prod.name if prod else ""
        if warnings:
            text = (
                _hdr("warn", "Ishlab chiqarish shubhali")
                + f"\nHujjat: <b>{pr.number}</b>\nMahsulot: {p_name}\n"
                + f"Miqdor: {fmt(qty)}\n\n" + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"production:{pr.id}")
        else:
            _log_activity(
                "🏭 IShL.CH.",
                f"<b>{pr.number}</b>: {p_name} {fmt(qty)} kg",
            )
    except Exception as e:
        print(f"[Audit] production xato: {e}", flush=True)
    finally:
        db.close()


# ============ 4) HARAJAT ============
def audit_expense(doc_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        doc = db.query(ExpenseDoc).filter(ExpenseDoc.id == doc_id).first()
        if not doc:
            return
        warnings: List[str] = []
        total = float(doc.total_amount or 0)

        if total >= BIG_EXPENSE:
            warnings.append(f"• Katta harajat: <b>{fmt(total)}</b> so'm")

        # Kassa balansi manfiyga tushdimi?
        if doc.cash_register_id:
            try:
                from app.services.finance_service import cash_balance_formula as _cash_balance_formula
                bal, _, _ = _cash_balance_formula(db, doc.cash_register_id)
                if bal < 0:
                    cr = db.query(CashRegister).filter(CashRegister.id == doc.cash_register_id).first()
                    cr_name = cr.name if cr else f"#{doc.cash_register_id}"
                    warnings.append(f"• Kassa <b>{cr_name}</b> manfiy: <b>{fmt(bal)}</b>")
            except Exception:
                pass

        # Takroriy — shu kassa + shu summa + oxirgi 24 soat
        since = datetime.now() - timedelta(hours=24)
        dup_count = db.query(ExpenseDoc).filter(
            ExpenseDoc.id != doc.id,
            ExpenseDoc.status == "confirmed",
            ExpenseDoc.cash_register_id == doc.cash_register_id,
            ExpenseDoc.total_amount == doc.total_amount,
            ExpenseDoc.created_at >= since,
        ).count()
        if dup_count:
            warnings.append(f"• Takror? 24 soat ichida shu kassada {dup_count} ta aynan shunday harajat")

        if warnings:
            text = (
                _hdr("warn", "Harajat shubhali")
                + f"\nHujjat: <b>{doc.number or '#' + str(doc.id)}</b>\n"
                + f"Summa: {fmt(total)}\n\n" + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"expense:{doc.id}")
        else:
            _log_activity(
                "💸 HARAJAT",
                f"<b>{doc.number or '#'+str(doc.id)}</b> — {fmt(total)} so'm",
            )
    except Exception as e:
        print(f"[Audit] expense xato: {e}", flush=True)
    finally:
        db.close()


# ============ 5) TO'LOV ============
def audit_payment(payment_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        pay = db.query(Payment).filter(Payment.id == payment_id).first()
        if not pay:
            return
        warnings: List[str] = []
        amount = float(pay.amount or 0)

        if amount >= BIG_PAYMENT:
            warnings.append(f"• Katta to'lov: <b>{fmt(amount)}</b> so'm")

        # Orphan — sale kategoriyasi bo'lib order_id va partner_id ikkalasi ham yo'q
        if (pay.category or "") == "sale" and not pay.order_id and not pay.partner_id:
            warnings.append("• Orphan: sale kategoriyali to'lovda order_id/partner_id yo'q")

        # Kassa balans manfiyligi
        if pay.cash_register_id:
            try:
                from app.services.finance_service import cash_balance_formula as _cash_balance_formula
                bal, _, _ = _cash_balance_formula(db, pay.cash_register_id)
                if bal < 0:
                    cr = db.query(CashRegister).filter(CashRegister.id == pay.cash_register_id).first()
                    cr_name = cr.name if cr else f"#{pay.cash_register_id}"
                    warnings.append(f"• Kassa <b>{cr_name}</b> manfiy: <b>{fmt(bal)}</b>")
            except Exception:
                pass

        if warnings:
            text = (
                _hdr("warn", "To'lov shubhali")
                + f"\nHujjat: <b>{pay.number or '#' + str(pay.id)}</b>\n"
                + f"Turi: {pay.type} / {pay.category or '—'}\n"
                + f"Summa: {fmt(amount)}\n\n" + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"payment:{pay.id}")
        else:
            icon = "💰" if pay.type == "income" else "💳"
            _log_activity(
                f"{icon} TO'LOV",
                f"<b>{pay.number or '#'+str(pay.id)}</b> [{pay.type}/{pay.category or '—'}] — {fmt(amount)} so'm",
            )
    except Exception as e:
        print(f"[Audit] payment xato: {e}", flush=True)
    finally:
        db.close()


# ============ 6) INVENTARIZATSIYA (STOCK ADJUSTMENT) ============
def audit_stock_adjustment(doc_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
        if not doc:
            return
        warnings: List[str] = []
        items = list(getattr(doc, "items", []) or [])
        big = []
        for it in items:
            new_q = float(it.quantity or 0)
            old_q = float(it.previous_quantity or 0) if it.previous_quantity is not None else new_q
            delta = new_q - old_q
            if abs(delta) < STOCK_ADJUST_DELTA:
                continue
            p = db.query(Product).filter(Product.id == it.product_id).first()
            if not p:
                continue
            sign = "+" if delta > 0 else ""
            big.append(f"• <b>{p.name}</b>: {sign}{fmt(delta)} ({fmt(old_q)} → {fmt(new_q)})")

        if big:
            warnings.append(f"• Katta farqlar: {len(big)} ta")
            warnings.extend(big[:8])

        wh = db.query(Warehouse).filter(Warehouse.id == doc.warehouse_id).first() if doc.warehouse_id else None
        wh_name = wh.name if wh else "—"
        doc_num = getattr(doc, "number", None) or f"#{doc.id}"
        if warnings:
            text = (
                _hdr("warn", "Inventarizatsiya shubhali")
                + f"\nHujjat: <b>{doc_num}</b>\nOmbor: {wh_name}\n\n" + _fmt_list(warnings, 12)
            )
            _push(text, dedup_key=f"inv:{doc.id}")
        else:
            _log_activity(
                "📋 INVENTAR",
                f"<b>{doc_num}</b> [{wh_name}] — {len(items)} ta pozitsiya",
            )
    except Exception as e:
        print(f"[Audit] stock_adjustment xato: {e}", flush=True)
    finally:
        db.close()


# ============ 7) DIGEST (scheduler har 30 daq) ============
def audit_digest():
    """Umumiy holat tahlili. Kam qoldiq — BU YERDA YO'Q (_scheduled_notifications_job
    tomonidan har 6 soatda alohida tekshiriladi). Bu yerda faqat real muammolar:
    manfiy stock, manfiy kassa, uzoq tasdiqlanmagan hujjatlar, orphan to'lovlar."""
    global _last_digest_sig
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        now = datetime.now()
        sections: List[str] = []

        # --- Manfiy qoldiqlar (float noise e'tiborsiz) ---
        neg = db.query(Stock, Product, Warehouse).join(
            Product, Stock.product_id == Product.id
        ).join(Warehouse, Stock.warehouse_id == Warehouse.id).filter(
            Stock.quantity < -NEG_STOCK_EPSILON,
            Product.is_active == True,
        ).order_by(Stock.quantity).limit(20).all()
        if neg:
            lines = [
                f"• <b>{p.name}</b> ({wh.name}): {float(s.quantity):,.3f}".rstrip("0").rstrip(".")
                for s, p, wh in neg
            ]
            sections.append(f"<b>🚨 Manfiy qoldiq ({len(neg)} ta):</b>\n" + _fmt_list(lines, 8))

        # --- Draft hujjatlar (uzoq vaqt tasdiqlanmagan) ---
        stale_cutoff = now - timedelta(hours=STALE_DRAFT_HOURS)
        stale_orders = db.query(Order).filter(
            Order.status == "draft",
            Order.created_at < stale_cutoff,
        ).count()
        stale_purchases = db.query(Purchase).filter(
            Purchase.status == "draft",
            Purchase.created_at < stale_cutoff,
        ).count()
        stale_expenses = db.query(ExpenseDoc).filter(
            ExpenseDoc.status == "draft",
            ExpenseDoc.created_at < stale_cutoff,
        ).count()
        stale_parts = []
        if stale_orders:
            stale_parts.append(f"sotuv: {stale_orders}")
        if stale_purchases:
            stale_parts.append(f"xarid: {stale_purchases}")
        if stale_expenses:
            stale_parts.append(f"harajat: {stale_expenses}")
        if stale_parts:
            sections.append(
                f"<b>📄 {STALE_DRAFT_HOURS} soat+ tasdiqlanmagan draft:</b>\n• "
                + ", ".join(stale_parts)
            )

        # --- Manfiy kassa balanslari ---
        try:
            from app.routes.finance import _cash_balance_formula
            neg_cash = []
            for cr in db.query(CashRegister).filter(CashRegister.is_active == True).all():
                try:
                    bal, _, _ = _cash_balance_formula(db, cr.id)
                    if bal < 0:
                        neg_cash.append(f"• <b>{cr.name}</b>: {fmt(bal)}")
                except Exception:
                    pass
            if neg_cash:
                sections.append("<b>🚨 Manfiy kassa balansi:</b>\n" + "\n".join(neg_cash[:5]))
        except Exception:
            pass

        # --- Bugungi harajat jami ---
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_expenses = db.query(func.coalesce(func.sum(ExpenseDoc.total_amount), 0)).filter(
            ExpenseDoc.status == "confirmed",
            ExpenseDoc.date >= today_start,
        ).scalar() or 0
        if float(today_expenses) >= HUGE_DAILY_EXPENSE:
            sections.append(f"<b>💸 Bugungi harajat:</b> {fmt(today_expenses)} so'm")

        if not sections:
            return  # muammo yo'q — xabar yubormaslik

        # --- Dedup: agar oxirgi digest bilan aynan bir xil bo'lsa, yubormaymiz ---
        body = "\n\n".join(sections)
        sig = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if sig == _last_digest_sig:
            return
        _last_digest_sig = sig

        text = _hdr("info", f"Digest {now.strftime('%H:%M')}") + "\n" + body
        _push(text)
    except Exception as e:
        print(f"[Audit] digest xato: {e}", flush=True)
    finally:
        db.close()


# ============ ACTIVITY PULSE FLUSH (scheduler har 10 daq) ============
def audit_activity_flush():
    """Activity bufferini Telegram ga bundle qilib yuborish."""
    if not AUDIT_ENABLED:
        return
    with _activity_lock:
        if not _activity_buffer:
            return
        entries = _activity_buffer[:]
        _activity_buffer.clear()
    # Truncate agar juda ko'p
    shown = entries[:ACTIVITY_FLUSH_LIMIT]
    body = "\n".join(shown)
    if len(entries) > ACTIVITY_FLUSH_LIMIT:
        body += f"\n... va yana {len(entries) - ACTIVITY_FLUSH_LIMIT} ta"
    text = _hdr("info", f"Faoliyat ({len(entries)} ta)") + "\n" + body
    try:
        _send_to_chats_sync(text, REALTIME_CHAT_IDS)
    except Exception as e:
        print(f"[Audit] activity flush TG xato: {e}", flush=True)


# ============ 8) KONVERSIYA (tayyor -> yarim_tayyor) ============
def audit_conversion(conv_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        conv = db.query(ProductConversion).filter(ProductConversion.id == conv_id).first()
        if not conv:
            return
        source = db.query(Product).filter(Product.id == conv.source_product_id).first()
        target = db.query(Product).filter(Product.id == conv.target_product_id).first()
        wh = db.query(Warehouse).filter(Warehouse.id == conv.warehouse_id).first()
        s_name = source.name if source else f"#{conv.source_product_id}"
        t_name = target.name if target else f"#{conv.target_product_id}"
        wh_name = wh.name if wh else f"#{conv.warehouse_id}"
        qty_kg = float(conv.quantity or 0)
        cost = float(conv.source_cost_price or 0)

        warnings: List[str] = []
        # Katta miqdor (20 kg+)
        if qty_kg >= 20:
            warnings.append(f"• Katta miqdor: <b>{qty_kg} kg</b>")
        # 24 soat ichida shu manba -> target uchun takror
        since = datetime.now() - timedelta(hours=24)
        dup = db.query(ProductConversion).filter(
            ProductConversion.id != conv.id,
            ProductConversion.source_product_id == conv.source_product_id,
            ProductConversion.target_product_id == conv.target_product_id,
            ProductConversion.status == "confirmed",
            ProductConversion.created_at >= since,
        ).count()
        if dup >= 2:
            warnings.append(f"• Takror? 24 soat ichida shu juftlik uchun {dup} ta konversiya")

        if warnings:
            text = (
                _hdr("warn", "Konversiya shubhali")
                + f"\nHujjat: <b>{conv.number}</b>\nOmbor: {wh_name}\n"
                + f"{s_name} → {t_name}\nMiqdor: {qty_kg} kg, 1 kg tannarx: {fmt(cost)}\n\n"
                + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"conv:{conv.id}")
        else:
            _log_activity(
                "♻️ KONVERSIYA",
                f"<b>{conv.number}</b>: {s_name} → {t_name} {qty_kg} kg ({wh_name})",
            )
    except Exception as e:
        print(f"[Audit] conversion xato: {e}", flush=True)
    finally:
        db.close()


# ============ 9) AGENT ORDER CONFIRM ============
def audit_agent_order_confirm(order_id: int):
    """Supervisor agent buyurtmasini tasdiqlaganda."""
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id, Order.source == "agent").first()
        if not o:
            return
        partner = db.query(Partner).filter(Partner.id == o.partner_id).first() if o.partner_id else None
        p_name = partner.name if partner else "—"
        items_count = db.query(OrderItem).filter(OrderItem.order_id == o.id).count()
        total = float(o.total or 0)
        debt = float(o.debt or 0)
        supervisor = db.query(User).filter(User.id == o.user_id).first() if o.user_id else None
        sup_name = supervisor.username if supervisor else "—"

        warnings: List[str] = []
        if items_count == 0:
            warnings.append("• Bo'sh buyurtma (qatorlar yo'q)")
        if debt >= BIG_SALE_DEBT:
            warnings.append(f"• Katta qarz: <b>{fmt(debt)}</b>")
        if partner and (partner.balance or 0) >= HUGE_PARTNER_DEBT:
            warnings.append(f"• Mijoz <b>{p_name}</b> jami qarzi: <b>{fmt(partner.balance)}</b>")

        if warnings:
            text = (
                _hdr("warn", "Agent buyurtma shubhali")
                + f"\nHujjat: <b>{o.number}</b>\nMijoz: {p_name}\n"
                + f"Summa: {fmt(total)}, qarz: {fmt(debt)}\nTasdiq: {sup_name}\n\n"
                + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"agent_order:{o.id}")
        else:
            _log_activity(
                "📦 AGENT BUYURTMA",
                f"<b>{o.number}</b>: {p_name} — {fmt(total)} so'm ({items_count} ta) — {sup_name}",
            )
    except Exception as e:
        print(f"[Audit] agent_order_confirm xato: {e}", flush=True)
    finally:
        db.close()


# ============ 10) KASSA-KASSAGA O'TKAZMA ============
def audit_cash_transfer(transfer_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        tr = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
        if not tr:
            return
        from_cr = db.query(CashRegister).filter(CashRegister.id == tr.from_cash_id).first() if tr.from_cash_id else None
        to_cr = db.query(CashRegister).filter(CashRegister.id == tr.to_cash_id).first() if tr.to_cash_id else None
        from_name = from_cr.name if from_cr else "—"
        to_name = to_cr.name if to_cr else "—"
        amount = float(tr.amount or 0)

        warnings: List[str] = []
        if amount >= BIG_PAYMENT:
            warnings.append(f"• Katta o'tkazma: <b>{fmt(amount)}</b>")
        # Chiqayotgan kassa manfiyga tushdimi?
        if tr.from_cash_id:
            try:
                from app.services.finance_service import cash_balance_formula as _cb
                bal, _, _ = _cb(db, tr.from_cash_id)
                if bal < 0:
                    warnings.append(f"• Kassa <b>{from_name}</b> manfiy: <b>{fmt(bal)}</b>")
            except Exception:
                pass

        if warnings:
            text = (
                _hdr("warn", "Kassa o'tkazma shubhali")
                + f"\n<b>{from_name}</b> → <b>{to_name}</b>\nSumma: {fmt(amount)}\n"
                + f"Holat: {tr.status}\n\n" + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"cash_transfer:{tr.id}")
        else:
            _log_activity(
                "💱 O'TKAZMA",
                f"{from_name} → {to_name}: {fmt(amount)} so'm [{tr.status}]",
            )
    except Exception as e:
        print(f"[Audit] cash_transfer xato: {e}", flush=True)
    finally:
        db.close()


# ============ 11) OMBORDAN OMBORGA O'TKAZMA ============
def audit_warehouse_transfer(transfer_id: int):
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        tr = db.query(WarehouseTransfer).filter(WarehouseTransfer.id == transfer_id).first()
        if not tr:
            return
        from_wh = db.query(Warehouse).filter(Warehouse.id == tr.from_warehouse_id).first() if tr.from_warehouse_id else None
        to_wh = db.query(Warehouse).filter(Warehouse.id == tr.to_warehouse_id).first() if tr.to_warehouse_id else None
        from_name = from_wh.name if from_wh else "—"
        to_name = to_wh.name if to_wh else "—"
        items = db.query(WarehouseTransferItem).filter(WarehouseTransferItem.transfer_id == tr.id).all()
        items_count = len(items)
        total_qty = sum(float(it.quantity or 0) for it in items)
        _log_activity(
            "🚚 OMBOR O'TKAZMA",
            f"<b>{tr.number}</b>: {from_name} → {to_name} — {items_count} ta pozitsiya (jami {total_qty} birlik)",
        )
    except Exception as e:
        print(f"[Audit] warehouse_transfer xato: {e}", flush=True)
    finally:
        db.close()


# ============ 12) DELIVERY STATUS ============
def audit_delivery_status(delivery_id: int, new_status: str, driver_name: str = "—"):
    """Haydovchi yetkazish statusini o'zgartirganda."""
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        dl = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not dl:
            return
        icon = {"picked_up": "📦", "in_progress": "🚗", "delivered": "✅", "failed": "❌"}.get(new_status, "•")
        order = db.query(Order).filter(Order.id == dl.order_id).first() if dl.order_id else None
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first() if order and order.partner_id else None
        p_name = partner.name if partner else "—"
        total = float(order.total or 0) if order else 0

        if new_status == "failed":
            # Shubhali — sabab aniqlash kerak
            text = (
                _hdr("alert", "Yetkazish BEKOR")
                + f"\n<b>{dl.number or '#' + str(dl.id)}</b>\n"
                + f"Mijoz: {p_name}\nSumma: {fmt(total)}\n"
                + f"Haydovchi: {driver_name}\n"
                + f"Izoh: {(dl.notes or '—')[:300]}"
            )
            _push(text, dedup_key=f"delivery_failed:{dl.id}")
        else:
            _log_activity(
                f"{icon} YETKAZISH",
                f"{dl.number or '#'+str(dl.id)}: {p_name} [{new_status}] — {driver_name}",
            )
    except Exception as e:
        print(f"[Audit] delivery_status xato: {e}", flush=True)
    finally:
        db.close()


# ============ 13) SOTUV BEKOR / O'CHIRISH ============
def audit_sale_cancel(order_id: int, action: str = "cancel"):
    """Sotuv bekor qilinganda yoki o'chirilganda."""
    if not _is_enabled():
        return
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id).first()
        if not o:
            return
        partner = db.query(Partner).filter(Partner.id == o.partner_id).first() if o.partner_id else None
        p_name = partner.name if partner else "—"
        total = float(o.total or 0)

        # Bekor qilish takrorlanayaptimi? 24 soat
        since = datetime.now() - timedelta(hours=24)
        cancelled_count = db.query(Order).filter(
            Order.status == "cancelled",
            Order.type == "sale",
            Order.updated_at >= since,
        ).count() if hasattr(Order, "updated_at") else 0

        warnings: List[str] = []
        if total >= BIG_SALE_DEBT:
            warnings.append(f"• Katta summa bekor: <b>{fmt(total)}</b>")
        if cancelled_count >= 3:
            warnings.append(f"• 24 soat ichida {cancelled_count} ta sotuv bekor qilingan — tekshirilsin")

        if warnings:
            text = (
                _hdr("alert", f"Sotuv {action}")
                + f"\n<b>{o.number}</b>\nMijoz: {p_name}\nSumma: {fmt(total)}\n\n"
                + _fmt_list(warnings)
            )
            _push(text, dedup_key=f"sale_{action}:{o.id}")
        else:
            _log_activity(
                f"🗑 SOTUV {action.upper()}",
                f"<b>{o.number}</b>: {p_name} — {fmt(total)} so'm",
            )
    except Exception as e:
        print(f"[Audit] sale_cancel xato: {e}", flush=True)
    finally:
        db.close()


# ============ 14) REVERT (umumiy) ============
def audit_revert(doc_type: str, doc_number: str, reason: str = "", user_name: str = "—"):
    """Ixtiyoriy hujjat turi uchun 'tasdiqdan bekor qilish' bildirishnomasi."""
    if not _is_enabled():
        return
    _log_activity(
        "↩️ REVERT",
        f"{doc_type} <b>{doc_number}</b> — {reason or 'tasdiq bekor'} [{user_name}]",
    )


# ============ TEST (qo'l bilan chaqirish uchun) ============
def audit_test_ping():
    """Audit tizimi ishlayaptimi tekshirish — test xabar (cooldownsiz)."""
    # Cooldownni o'chirib, to'g'ridan-to'g'ri yuboramiz
    try:
        _send_to_chats_sync(
            _hdr("ok", "Test") + "\nAudit watchdog ishlayapti ✓",
            REALTIME_CHAT_IDS,
        )
    except Exception as e:
        print(f"[Audit] test xato: {e}", flush=True)
