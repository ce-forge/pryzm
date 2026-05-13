"""add workspace engine_config

Revision ID: 78445f9618d3
Revises: a3f2c1d4e5b6
Create Date: 2026-05-14 06:48:31.176441

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "78445f9618d3"
down_revision: Union[str, Sequence[str], None] = "a3f2c1d4e5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_ENGINE_CONFIG = '{"backend": "ollama", "model": "gemma4:e4b"}'


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("engine_config", JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.execute(
        """
        UPDATE workspaces
        SET engine_config = jsonb_build_object(
            'backend', 'ollama',
            'model', COALESCE(preferred_model, 'gemma4:e4b')
        )
        WHERE engine_config IS NULL
        """
    )

    op.alter_column(
        "workspaces", "engine_config",
        existing_type=JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_ENGINE_CONFIG}'::jsonb"),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "engine_config")
