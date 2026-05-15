"""Verifies the tsvector column + GIN index for keyword search.

Both come from migration 7a91b3e2d5c1 alongside the HNSW swap.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_tsvector_column_exists_and_is_generated(db_at_head):
    """`content_tsv` is a GENERATED ALWAYS AS STORED column using the
    `simple` config — verified at the catalog level so we catch
    accidental config drift (e.g., switching to `english` would break
    identifier-string matching)."""
    engine = db_at_head
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT generation_expression
            FROM information_schema.columns
            WHERE table_name = 'document_chunks'
              AND column_name = 'content_tsv'
        """)).first()
    assert row is not None, "content_tsv column does not exist"
    expr = (row[0] or "").lower()
    assert "to_tsvector" in expr
    assert "simple" in expr, f"tsvector config should be 'simple', got: {expr}"


def test_gin_index_exists_on_tsvector(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'ix_chunks_content_tsv'
        """)).first()
    assert row is not None, "ix_chunks_content_tsv does not exist"
    indexdef = row[0].lower()
    assert "gin" in indexdef


def test_tsvector_auto_populates_on_insert(db_at_head):
    """Insert a chunk, read back content_tsv — verifies the GENERATED
    expression fires automatically (no app-side trigger needed)."""
    engine = db_at_head
    with engine.connect() as conn:
        # Seed a minimal workspace + document so the FK constraints pass.
        conn.execute(text("INSERT INTO workspaces (id, slug, display_name, system_prompt) VALUES ('ws-tsv', 'tsv', 'TSV', '')"))
        conn.execute(text("INSERT INTO documents (id, filename, workspace_id) VALUES ('doc-tsv', 'x.txt', 'ws-tsv')"))
        conn.execute(text("""
            INSERT INTO document_chunks (id, document_id, workspace_id, content)
            VALUES ('chunk-tsv', 'doc-tsv', 'ws-tsv', 'Username admin Password nfsyg9yehhp9bt9x')
        """))
        conn.commit()
        tsv = conn.execute(text(
            "SELECT content_tsv::text FROM document_chunks WHERE id = 'chunk-tsv'"
        )).scalar()
    # The simple config tokenizes lowercased + no stemming.
    # `nfsyg9yehhp9bt9x` survives as a single token (no punctuation breaks).
    assert "admin" in tsv
    assert "nfsyg9yehhp9bt9x" in tsv


def test_downgrade_drops_tsvector(reset_test_db, alembic_cfg):
    """Downgrade past the migration removes the column AND its index."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "53f0bcb1ae0d")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'document_chunks' AND column_name = 'content_tsv'
        """)).scalar()
        idx = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_content_tsv'
        """)).scalar()
    engine.dispose()
    assert col is None
    assert idx is None
