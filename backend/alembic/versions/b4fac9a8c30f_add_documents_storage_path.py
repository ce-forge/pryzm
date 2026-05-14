"""add documents.storage_path

VLM Milestone 2 (docs/specs/2026-05-15-image-upload-vlm.md): images
become first-class persistent attachments. The new column carries the
filesystem path to the original bytes saved at upload time, so the
ai_engine can re-attach the image when an image-derived chunk is
selected by RAG (Milestone 3 wires that up).

Nullable on purpose: text documents don't have an original-file form,
so storage_path stays NULL for them. The presence/absence of the
column is what callers check.

Revision ID: b4fac9a8c30f
Revises: de5dfc455310
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4fac9a8c30f"
down_revision: Union[str, Sequence[str], None] = "de5dfc455310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("storage_path", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "storage_path")
