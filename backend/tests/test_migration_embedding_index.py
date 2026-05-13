"""Verifies migration D: ivfflat index on document_chunks.embedding."""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_index_exists_with_correct_method_and_opclass(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'ix_chunks_embedding'
        """)).first()
    assert row is not None, "ix_chunks_embedding does not exist"
    indexdef = row[1].lower()
    assert "ivfflat" in indexdef
    assert "vector_cosine_ops" in indexdef


def test_downgrade_drops_index(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "f3ae59ae02f5")  # T4's down_revision

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        idx = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_embedding'
        """)).scalar()
    engine.dispose()
    assert idx is None
