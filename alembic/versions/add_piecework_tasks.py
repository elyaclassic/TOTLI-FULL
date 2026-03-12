"""add piecework_tasks table and employee.piecework_task_id

Revision ID: add_piecework_tasks
Revises: add_emp_sal_rates
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "add_piecework_tasks"
down_revision: Union[str, Sequence[str], None] = "add_emp_sal_rates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, name):
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
    if not _has_table(conn, "piecework_tasks"):
        op.create_table(
            "piecework_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), unique=True, nullable=True),
            sa.Column("name", sa.String(200), nullable=True),
            sa.Column("price_per_unit", sa.Float(), default=0),
            sa.Column("unit_name", sa.String(50), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), default=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if not _has_column(conn, "employees", "piecework_task_id"):
        op.add_column("employees", sa.Column("piecework_task_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "piecework_task_id")
    op.drop_table("piecework_tasks")
