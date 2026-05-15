"""HNSW index + tsvector column for hybrid (vector + keyword) retrieval

Revision ID: 7a91b3e2d5c1
Revises: 53f0bcb1ae0d
Create Date: 2026-05-15 19:00:00.000000

Replaces IVFFlat with HNSW on document_chunks.embedding for better recall
at the same query latency as the chunk count grows. Adds a tsvector column
(`content_tsv`) with the `simple` config — no stemming, identifier-friendly,
matches our content mix of natural-language captions with embedded usernames
/ IDs / error codes / IP addresses. Adds a GIN index on the tsvector for
keyword search. Hybrid retrieval merges both via RRF in services/knowledge.py.

Why the `simple` config:
- Our content carries identifier-class strings ("nfsyg9yehhp9bt9x",
  "LAPTOP-042", error codes). The `english` config stems these (e.g.
  "passwords" → "password") which breaks exact identifier matching.
- Semantic similarity for natural-language is already covered by the
  vector side; keyword side's job is verbatim string lookup.

The tsvector column is GENERATED ALWAYS AS STORED, so new INSERTs auto-
populate without an app-side trigger or write path change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "7a91b3e2d5c1"
down_revision: Union[str, Sequence[str], None] = "53f0bcb1ae0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- vector index: IVFFlat → HNSW ----
    # HNSW has better recall/quality tradeoff at the same latency as the
    # corpus grows. Drop the IVFFlat created in 50d45d7ba8d6, create HNSW
    # in its place. CONCURRENTLY for both so writes stay unblocked; needs
    # to run outside the migration's wrapping transaction.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_embedding")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_embedding_hnsw "
            "ON document_chunks USING hnsw "
            "(embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )

    # ---- keyword side: tsvector column + GIN index ----
    # GENERATED ALWAYS AS STORED auto-populates on insert/update — no
    # trigger needed and existing rows are backfilled in the ALTER TABLE.
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_content_tsv "
            "ON document_chunks USING gin (content_tsv)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_content_tsv")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_tsv")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_embedding_hnsw")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_embedding "
            "ON document_chunks USING ivfflat "
            "(embedding vector_cosine_ops) WITH (lists = 100)"
        )
