"""add attendances, attendance_docs, employee_advances; salaries.advance_deduction

Revision ID: add_att_adv
Revises: add_piecework_tasks
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "add_att_adv"
down_revision: Union[str, Sequence[str], None] = "add_piecework_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, name: str) -> bool:
    if conn.dialect.name == "sqlite":
        r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name})
        return r.fetchone() is not None
    return False


def _has_column(conn, table: str, column: str) -> bool:
    if conn.dialect.name == "sqlite":
        r = conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in r)
    return False


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "attendances"):
        op.create_table(
            "attendances",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("check_in", sa.DateTime(), nullable=True),
            sa.Column("check_out", sa.DateTime(), nullable=True),
            sa.Column("hours_worked", sa.Float(), default=0),
            sa.Column("status", sa.String(20), default="present"),
            sa.Column("event_snapshot_path", sa.String(255), nullable=True),
            sa.Column("note", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if not _has_table(conn, "attendance_docs"):
        op.create_table(
            "attendance_docs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("number", sa.String(50), unique=True, nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if not _has_table(conn, "employee_advances"):
        op.create_table(
            "employee_advances",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
            sa.Column("amount", sa.Float(), default=0),
            sa.Column("advance_date", sa.Date(), nullable=False),
            sa.Column("note", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if _has_table(conn, "salaries") and not _has_column(conn, "salaries", "advance_deduction"):
        op.add_column("salaries", sa.Column("advance_deduction", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_table("employee_advances")
    op.drop_table("attendance_docs")
    op.drop_table("attendances")
    conn = op.get_bind()
    if _has_column(conn, "salaries", "advance_deduction"):
        op.drop_column("salaries", "advance_deduction")
