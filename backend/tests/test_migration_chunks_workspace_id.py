"""Verifies migration B: document_chunks.workspace_id FK + NOT NULL + composite index."""
import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


def _seed_workspace(engine, slug: str) -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES (:id, :slug, 'x', '', '[]'::jsonb, false)
        """), {"id": slug, "slug": slug})
    return slug


def _seed_document(engine, doc_id: str, workspace_id: str) -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO documents (id, filename, workspace_id, is_global)
            VALUES (:id, 'f.txt', :ws, false)
        """), {"id": doc_id, "ws": workspace_id})
    return doc_id


def test_workspace_id_backfilled_from_parent_document(db_at_revision, alembic_cfg):
    # Start at T1's head (engine_config exists, but no workspace_id on chunks yet).
    engine = db_at_revision("78445f9618d3")
    ws = _seed_workspace(engine, "ws-backfill")
    doc = _seed_document(engine, "doc-1", ws)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO document_chunks (id, document_id, content)
            VALUES ('chunk-1', :doc, 'hello')
        """), {"doc": doc})
    engine.dispose()

    command.upgrade(alembic_cfg, "+1")

    url = alembic_cfg.get_main_option("sqlalchemy.url")
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as conn:
        chunk_ws = conn.execute(text(
            "SELECT workspace_id FROM document_chunks WHERE id = 'chunk-1'"
        )).scalar()
    engine.dispose()
    assert chunk_ws == ws


def test_workspace_id_is_not_null_after_migration(db_at_head):
    engine = db_at_head
    ws = _seed_workspace(engine, "ws-null-test")
    doc = _seed_document(engine, "doc-null", ws)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO document_chunks (id, document_id, content)
                VALUES ('chunk-null', :doc, 'oops')
            """), {"doc": doc})


def test_composite_index_exists(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        indexdef = conn.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'ix_chunks_workspace_document'
        """)).scalar()
    assert indexdef is not None
    # Verify it's a composite index on (workspace_id, document_id).
    assert "workspace_id" in indexdef
    assert "document_id" in indexdef


def test_fk_cascades_workspace_delete(db_at_head):
    engine = db_at_head
    ws = _seed_workspace(engine, "ws-cascade")
    doc = _seed_document(engine, "doc-cascade", ws)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO document_chunks (id, document_id, workspace_id, content)
            VALUES ('chunk-cascade', :doc, :ws, 'x')
        """), {"doc": doc, "ws": ws})

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": ws})
        remaining = conn.execute(text(
            "SELECT count(*) FROM document_chunks WHERE id = 'chunk-cascade'"
        )).scalar()
    assert remaining == 0


def test_downgrade_drops_column_and_index(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "78445f9618d3")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'document_chunks' AND column_name = 'workspace_id'
        """)).scalar()
        idx = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_workspace_document'
        """)).scalar()
    engine.dispose()
    assert col is None
    assert idx is None
