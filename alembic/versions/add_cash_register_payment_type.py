"""add payment_type to cash_registers (naqd, plastik, click, terminal)

Revision ID: cash_payment_type
Revises: stock_movement_track
Create Date: 2026-02-13

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = "cash_payment_type"
down_revision: Union[str, Sequence[str], None] = "stock_movement_track"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    if conn.dialect.name == "sqlite":
        r = conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in r)
    return False


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "cash_registers", "payment_type"):
        op.add_column("cash_registers", sa.Column("payment_type", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("cash_registers", "payment_type")
