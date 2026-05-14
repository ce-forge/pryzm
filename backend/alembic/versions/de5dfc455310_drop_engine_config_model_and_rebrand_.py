"""drop engine_config model and rebrand backend

Revision ID: de5dfc455310
Revises: bf317b5870ef
Create Date: 2026-05-14 17:30:33.628499

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "de5dfc455310"
down_revision = "bf317b5870ef"
branch_labels = None
depends_on = None


NEW_DEFAULT = '{"backend": "llama_cpp"}'
OLD_DEFAULT = '{"backend": "ollama", "model": "gemma4:e4b"}'


def upgrade() -> None:
    # Strip the 'model' key and rebrand the 'backend' value on every row.
    op.execute(
        "UPDATE workspaces SET engine_config = "
        "(engine_config - 'model') || jsonb_build_object('backend', 'llama_cpp')"
    )
    # Update the column's server default to match.
    op.alter_column(
        "workspaces",
        "engine_config",
        server_default=sa.text(f"'{NEW_DEFAULT}'::jsonb"),
    )


def downgrade() -> None:
    # Restore the model key on every row, defaulting to gemma4:e4b. (We don't
    # remember per-workspace model picks here — the only path that wrote it
    # was the model picker, which gets reinstated by the surrounding code
    # revert.)
    op.execute(
        "UPDATE workspaces SET engine_config = "
        "jsonb_build_object('backend', 'ollama', 'model', 'gemma4:e4b')"
    )
    op.alter_column(
        "workspaces",
        "engine_config",
        server_default=sa.text(f"'{OLD_DEFAULT}'::jsonb"),
    )
