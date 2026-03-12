#!/usr/bin/env python3
"""
Baza backup skripti — cron yoki qo'lda ishlatish uchun.
Ishga tushirish: python backup_db.py
"""
import os
import sys

# Loyiha ildiziga qo'shish
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.backup import do_backup, cleanup_old_backups

if __name__ == "__main__":
    try:
        path = do_backup(subdir="daily")
        n = cleanup_old_backups(keep_count=30, subdir="daily")
        print("OK:", path)
        if n:
            print("Eski nusxalar o'chirildi:", n)
    except Exception as e:
        print("Xato:", e, file=sys.stderr)
        sys.exit(1)
