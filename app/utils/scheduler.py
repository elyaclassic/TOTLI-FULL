"""
Reja (scheduler) — kunlik/vaqtli vazifalar.
Kam qolgan tovar va muddati o'tgan qarzlar uchun bildirishnoma yaratadi.
Kunlik avtomatik baza backup.
"""

import os
import shutil
import glob
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from app.models.database import SessionLocal, Order
from app.utils.notifications import check_low_stock_and_notify, create_notification

# Baza fayli va backup papkasi
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB_PATH = os.path.join(_BASE_DIR, "totli_holva.db")
_MAX_BACKUPS = 14  # Oxirgi 14 kunlik backup saqlanadi


def _scheduled_notifications_job():
    """Har ishga tushganda: kam qoldiq tekshiruvi va muddati o'tgan qarzlar bildirishnomasi."""
    db = SessionLocal()
    try:
        # 1) Kam qolgan tovarlar
        n_low = check_low_stock_and_notify(db)
        # 2) Muddati o'tgan qarzlar (sotuvda qarz > 0, 7+ kun oldin)
        overdue_cutoff = datetime.now() - timedelta(days=7)
        overdue = db.query(Order).filter(
            Order.type == "sale",
            Order.debt > 0,
            Order.created_at < overdue_cutoff,
        ).all()
        if overdue:
            total_debt = sum(o.debt for o in overdue)
            create_notification(
                db,
                title="Muddati o'tgan qarzlar",
                message=f"{len(overdue)} ta buyurtmada jami {total_debt:,.0f} so'm qarz muddati o'tgan (7+ kun).",
                notification_type="warning",
                priority="high",
                action_url="/reports/debts",
                related_entity_type="order",
            )
    except Exception as e:
        print(f"[Scheduler] xato: {e}")
    finally:
        db.close()


def _daily_backup_job():
    """Kunlik avtomatik baza backup — oxirgi 14 ta saqlanadi."""
    try:
        if not os.path.exists(_DB_PATH):
            print(f"[Backup] Baza topilmadi: {_DB_PATH}")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = f"totli_holva_backup_{timestamp}.db"
        backup_path = os.path.join(_BASE_DIR, backup_name)
        shutil.copy2(_DB_PATH, backup_path)
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        print(f"[Backup] Saqlandi: {backup_name} ({size_mb:.1f} MB)")
        # Eski backuplarni tozalash
        pattern = os.path.join(_BASE_DIR, "totli_holva_backup_*.db")
        backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        for old in backups[_MAX_BACKUPS:]:
            os.remove(old)
            print(f"[Backup] Eski backup o'chirildi: {os.path.basename(old)}")
    except Exception as e:
        print(f"[Backup] Xato: {e}")


_scheduler = None


def start_scheduler():
    """Scheduler ni ishga tushiradi — har 6 soatda bildirishnomalar, kunlik backup."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_scheduled_notifications_job, "interval", hours=6, id="notifications")
    _scheduler.add_job(_scheduled_notifications_job, "date", run_date=datetime.now() + timedelta(minutes=1), id="notifications_first")
    # Kunlik backup — har kuni soat 23:00 da
    _scheduler.add_job(_daily_backup_job, "cron", hour=23, minute=0, id="daily_backup")
    # Hozir ham bir marta backup olish
    _scheduler.add_job(_daily_backup_job, "date", run_date=datetime.now() + timedelta(seconds=10), id="backup_first")
    _scheduler.start()
    print("[Scheduler] Reja ishga tushdi (bildirishnomalar + kunlik backup soat 23:00)")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
