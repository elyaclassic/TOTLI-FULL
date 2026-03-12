"""add employee hire document fields (passport, photo, salary_type)

Revision ID: add_emp_hire_doc
Revises: add_emp_att_adv_sal
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "add_emp_hire_doc"
down_revision: Union[str, Sequence[str], None] = "add_emp_att_adv_sal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    if conn.dialect.name == "sqlite":
        r = conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in r)
    return False


def upgrade() -> None:
    conn = op.get_bind()
    for col, type_sa in [
        ("salary_type", sa.String(50)),
        ("passport_series", sa.String(20)),
        ("passport_number", sa.String(30)),
        ("passport_issued_by", sa.String(255)),
        ("passport_issued_date", sa.Date()),
        ("photo", sa.String(500)),
    ]:
        if not _has_column(conn, "employees", col):
            op.add_column("employees", sa.Column(col, type_sa, nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "photo")
    op.drop_column("employees", "passport_issued_date")
    op.drop_column("employees", "passport_issued_by")
    op.drop_column("employees", "passport_number")
    op.drop_column("employees", "passport_series")
    op.drop_column("employees", "salary_type")
