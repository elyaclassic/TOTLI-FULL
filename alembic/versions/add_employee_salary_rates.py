"""add employee salary hourly and piece rates

Revision ID: add_emp_sal_rates
Revises: add_emp_hire_doc
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "add_emp_sal_rates"
down_revision: Union[str, Sequence[str], None] = "add_emp_hire_doc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    if conn.dialect.name == "sqlite":
        r = conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in r)
    return False


def upgrade() -> None:
    conn = op.get_bind()
    for col in ["salary_hourly_rate", "salary_piece_rate"]:
        if not _has_column(conn, "employees", col):
            op.add_column("employees", sa.Column(col, sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "salary_piece_rate")
    op.drop_column("employees", "salary_hourly_rate")
