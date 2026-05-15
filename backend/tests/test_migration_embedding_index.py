"""Verifies the embedding index on document_chunks.

Originally an IVFFlat index (migration 50d45d7ba8d6); swapped to HNSW
in migration 7a91b3e2d5c1 for better recall at the same query latency
as the corpus grows. Test names retained for git-history continuity
even though they now assert against the HNSW name + method.
"""
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
              AND indexname = 'ix_chunks_embedding_hnsw'
        """)).first()
    assert row is not None, "ix_chunks_embedding_hnsw does not exist"
    indexdef = row[1].lower()
    assert "hnsw" in indexdef
    assert "vector_cosine_ops" in indexdef


def test_downgrade_restores_ivfflat_index(reset_test_db, alembic_cfg):
    """Downgrading the HNSW migration drops the HNSW index and recreates
    the original IVFFlat one. Round-trip safety check."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    # 53f0bcb1ae0d is the revision immediately before 7a91b3e2d5c1.
    # Downgrading TO that revision undoes the HNSW migration but keeps
    # everything earlier in place — including the original IVFFlat index.
    command.downgrade(alembic_cfg, "53f0bcb1ae0d")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        hnsw_exists = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw'
        """)).scalar()
        ivfflat_exists = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_embedding'
        """)).scalar()
    engine.dispose()
    assert hnsw_exists is None
    assert ivfflat_exists is not None
