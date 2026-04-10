"""
Reja (scheduler) — kunlik/vaqtli vazifalar.
Kam qolgan tovar va muddati o'tgan qarzlar uchun bildirishnoma yaratadi.
Kunlik avtomatik baza backup.
Hikvision dan kunlik davomat yuklash.
"""

import os
import sqlite3
import glob
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from app.models.database import SessionLocal, Order, Notification, AttendanceDoc, Attendance, Employee
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
        # 24 soat ichida takroriy bildirishnoma yaratilmasin
        since = datetime.now() - timedelta(hours=24)
        existing_debt_notif = db.query(Notification).filter(
            Notification.title == "Muddati o'tgan qarzlar",
            Notification.created_at >= since,
        ).first()
        if not existing_debt_notif:
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


# Hikvision sozlamalari — .env faylidan o'qiladi
_HIKVISION_HOST = os.environ.get("HIKVISION_HOST", "")
_HIKVISION_PORT = int(os.environ.get("HIKVISION_PORT", "443") or "443")
_HIKVISION_USERNAME = os.environ.get("HIKVISION_USERNAME", "")
_HIKVISION_PASSWORD = os.environ.get("HIKVISION_PASSWORD", "")

if not (_HIKVISION_HOST and _HIKVISION_USERNAME and _HIKVISION_PASSWORD):
    print("[Scheduler] OGOHLANTIRISH: HIKVISION_* env o'zgaruvchilari to'liq emas — davomat sync ishlamaydi")


def _daily_hikvision_sync_job():
    """Har kuni Hikvision dan shu kungi davomatni avtomatik yuklash.
    Birinchi kelish va oxirgi ketish vaqti bo'yicha."""
    db = SessionLocal()
    try:
        from app.utils.hikvision import sync_hikvision_attendance
        today = date.today()
        yesterday = today - timedelta(days=1)
        result = sync_hikvision_attendance(
            hikvision_host=_HIKVISION_HOST,
            hikvision_port=_HIKVISION_PORT,
            hikvision_username=_HIKVISION_USERNAME,
            hikvision_password=_HIKVISION_PASSWORD,
            start_date=yesterday,
            end_date=today,
            db_session=db,
        )
        imported = result.get("imported", 0)
        events = result.get("events_count", 0)
        errors = result.get("errors", [])
        print(f"[Hikvision Sync] {today}: hodisa={events}, yuklangan={imported}, xato={len(errors)}")
        if errors:
            for err in errors[:3]:
                print(f"  [Hikvision] {err}")
    except Exception as e:
        print(f"[Hikvision Sync] xato: {e}")
    finally:
        db.close()


def _sqlite_online_backup(src: str, dest: str):
    """sqlite3 online backup API — WAL-safe, jonli yozish paytida xavfsiz."""
    src_conn = sqlite3.connect(src)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            with dest_conn:
                src_conn.backup(dest_conn, pages=0)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _daily_backup_job():
    """Kunlik avtomatik baza backup — oxirgi 14 ta saqlanadi.
    sqlite3.backup() API ishlatiladi (WAL-safe)."""
    try:
        if not os.path.exists(_DB_PATH):
            print(f"[Backup] Baza topilmadi: {_DB_PATH}")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = f"totli_holva_backup_{timestamp}.db"
        backup_path = os.path.join(_BASE_DIR, backup_name)
        _sqlite_online_backup(_DB_PATH, backup_path)
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


def _live_backup_job():
    """Har 5 daqiqada — jonli backup (sqlite3.backup() API + gzip).
    scripts/backup_live.py ga delegatsiya qilinadi."""
    try:
        import sys
        _scripts_dir = os.path.join(_BASE_DIR, "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from backup_live import run_live_backup
        r = run_live_backup(send_alert_on_fail=True)
        if not r.get("ok"):
            print(f"[LiveBackup] FAIL: {r.get('error')}")
    except Exception as e:
        print(f"[LiveBackup] Xato: {e}")


def _create_attendance_for_date(target_date):
    """Berilgan sana uchun tabel hujjati va davomat yozuvlarini yaratish."""
    db = SessionLocal()
    try:
        doc = db.query(AttendanceDoc).filter(AttendanceDoc.date == target_date).first()
        if not doc:
            doc_number = f"T-{target_date.strftime('%Y-%m-%d')}"
            doc = AttendanceDoc(number=doc_number, date=target_date, confirmed_at=datetime.now())
            db.add(doc)
            db.flush()
            print(f"[Tabel] Kunlik tabel yaratildi va tasdiqlandi: {doc_number}")
        elif not doc.confirmed_at:
            doc.confirmed_at = datetime.now()
            print(f"[Tabel] Tabel tasdiqlandi: {doc.number}")

        active_employees = db.query(Employee).filter(Employee.is_active == True).all()
        created = 0
        for emp in active_employees:
            existing = db.query(Attendance).filter(
                Attendance.employee_id == emp.id,
                Attendance.date == target_date,
            ).first()
            if not existing:
                att = Attendance(
                    employee_id=emp.id,
                    date=target_date,
                    doc_id=doc.id,
                    status="absent",
                )
                db.add(att)
                created += 1
        db.commit()
        if created:
            print(f"[Tabel] {target_date}: {created} ta xodim uchun davomat yozuvi yaratildi")
    except Exception as e:
        db.rollback()
        print(f"[Tabel] Xato ({target_date}): {e}")
    finally:
        db.close()


def _daily_attendance_create():
    """Bugun va o'tkazib yuborilgan kunlar uchun tabel yaratish."""
    today = date.today()
    # Oxirgi tabel sanasini topish — undan bugunga qadar bo'sh kunlarni to'ldirish
    db = SessionLocal()
    try:
        last_doc = db.query(AttendanceDoc).order_by(AttendanceDoc.date.desc()).first()
        if last_doc:
            start = last_doc.date + timedelta(days=1)
        else:
            start = today
        # O'tkazib yuborilgan kunlarni to'ldirish (max 30 kun)
        current = start
        while current <= today:
            if (today - current).days > 30:
                current += timedelta(days=1)
                continue
            _create_attendance_for_date(current)
            current += timedelta(days=1)
    except Exception as e:
        print(f"[Tabel] Xato: {e}")
    finally:
        db.close()




def _tg_daily_summary():
    """Kechqurun — kunlik yakuniy hisobot (@RD2197 uchun)"""
    try:
        from app.bot.services.notifier import send_daily_summary
        send_daily_summary()
    except Exception as e:
        print(f"[Scheduler] TG daily summary xato: {e}")


def _tg_audit_digest():
    """Har 30 daqiqada — audit watchdog digest (@elya_classic uchun).
    Manfiy qoldiq, kam qoldiq, orphan to'lov, uzoq tasdiqlanmagan hujjatlar va h.k."""
    try:
        from app.bot.services.audit_watchdog import audit_digest
        audit_digest()
    except Exception as e:
        print(f"[Scheduler] Audit digest xato: {e}")




_scheduler = None


def start_scheduler():
    """Scheduler ni ishga tushiradi — har 6 soatda bildirishnomalar, kunlik backup, Hikvision sync."""
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
    # Jonli backup — har 5 daqiqada (sqlite3 online backup + gzip, retention 2 soat)
    _scheduler.add_job(
        _live_backup_job,
        "interval",
        minutes=5,
        id="live_backup",
        replace_existing=True,
        misfire_grace_time=120,
        coalesce=True,
        max_instances=1,
    )
    # Ishga tushganda 30 soniya keyin bir marta (birinchi snapshot uchun)
    _scheduler.add_job(_live_backup_job, "date", run_date=datetime.now() + timedelta(seconds=30), id="live_backup_first")
    # Hikvision davomat yuklash — har kuni soat 22:00 da (ish kuni tugagach)
    _scheduler.add_job(_daily_hikvision_sync_job, "cron", hour=22, minute=0, id="hikvision_daily")
    # Har 10 daqiqada sync qilish (kun davomida yangilanib turishi uchun)
    _scheduler.add_job(_daily_hikvision_sync_job, "interval", minutes=10, id="hikvision_interval")
    # Hozir ham bir marta yuklash
    _scheduler.add_job(_daily_hikvision_sync_job, "date", run_date=datetime.now() + timedelta(minutes=2), id="hikvision_first")
    # Kunlik tabel yaratish — har kuni soat 07:00 da
    _scheduler.add_job(_daily_attendance_create, "cron", hour=7, minute=0, id="daily_attendance")
    # Hozir ham bir marta yaratish
    _scheduler.add_job(_daily_attendance_create, "date", run_date=datetime.now() + timedelta(seconds=15), id="attendance_first")
    # Telegram: kechqurun 21:00 — kunlik yakuniy hisobot (@RD2197)
    _scheduler.add_job(_tg_daily_summary, "cron", hour=21, minute=0, id="tg_daily_summary")
    # Audit watchdog digest — har 30 daqiqada (@elya_classic)
    _scheduler.add_job(_tg_audit_digest, "interval", minutes=30, id="tg_audit_digest")
    # Ishga tushganda 5 daqiqa keyin bir marta digest (tizim stabillashishi uchun)
    _scheduler.add_job(_tg_audit_digest, "date", run_date=datetime.now() + timedelta(minutes=5), id="tg_audit_digest_first")
    _scheduler.start()
    print("[Scheduler] Reja ishga tushdi (bildirishnomalar + backup + live backup (5min) + Hikvision sync + TG notify + Audit)")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
