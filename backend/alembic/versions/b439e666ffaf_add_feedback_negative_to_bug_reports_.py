"""add feedback_negative to bug_reports category check

Revision ID: b439e666ffaf
Revises: a7c1d3b9e2f4
Create Date: 2026-05-21 00:06:43.813703

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b439e666ffaf'
down_revision: Union[str, Sequence[str], None] = 'a7c1d3b9e2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("bug_reports_category_check", "bug_reports", type_="check")
    op.create_check_constraint(
        "bug_reports_category_check",
        "bug_reports",
        "category IN ('incorrect_info','vision_wrong','tool_error',"
        "'slow','ui_bug','feedback_negative','other')",
    )


def downgrade() -> None:
    op.drop_constraint("bug_reports_category_check", "bug_reports", type_="check")
    op.create_check_constraint(
        "bug_reports_category_check",
        "bug_reports",
        "category IN ('incorrect_info','vision_wrong','tool_error',"
        "'slow','ui_bug','other')",
    )
