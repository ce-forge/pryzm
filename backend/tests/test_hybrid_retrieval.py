"""Tests for the hybrid (vector + keyword) retrieval path.

The two engines do different jobs:
- Vector search: semantic similarity. Wins on conversational queries.
- Keyword search (tsvector): exact-token matching. Wins on identifier
  strings, error codes, usernames, IPs.

RRF (Reciprocal Rank Fusion) merges both into one ranked list — chunks
appearing in either list rank well; chunks in both rank best.
"""
from __future__ import annotations

from db import models
from services import knowledge


def _seed_workspace(db, slug="hybrid-test"):
    user = models.User(
        id=f"user-{slug}", username=slug, password_hash="hash", is_admin=False
    )
    ws = models.Workspace(
        id=f"ws-{slug}",
        slug=slug,
        display_name="Hybrid Test",
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        user_id=f"user-{slug}",
    )
    db.add(user); db.commit()
    db.add(ws); db.commit(); return ws


def _seed_session(db, ws_id, slug):
    ws = db.query(models.Workspace).filter_by(id=ws_id).one()
    s = models.Session(id=f"sess-{slug}", title="t", workspace_id=ws_id, user_id=ws.user_id)
    db.add(s); db.commit(); return s


def _seed_chunk(db, ws, session, filename, content, embedding=None):
    """Create a Document + a single DocumentChunk with optional explicit
    embedding. Default embedding is all-0.5 so vector distance is a fixed
    midpoint regardless of query — keyword side does the lifting in tests."""
    doc = models.Document(filename=filename, workspace_id=ws.id, session_id=session.id)
    db.add(doc); db.commit(); db.refresh(doc)
    chunk = models.DocumentChunk(
        document_id=doc.id,
        workspace_id=ws.id,
        content=content,
        embedding=embedding or [0.5] * 768,
    )
    db.add(chunk); db.commit(); db.refresh(chunk)
    return chunk


# ---------------------------------------------------------------------------
# Keyword side
# ---------------------------------------------------------------------------

def test_keyword_search_finds_exact_identifier_string(db_session):
    """The whole point of adding keyword search: find chunks containing
    a specific identifier string (password, ID, error code) that vector
    similarity can't reliably surface."""
    ws = _seed_workspace(db_session, "kw-exact")
    sess = _seed_session(db_session, ws.id, "kw-exact")
    _seed_chunk(db_session, ws, sess, "creds.txt",
                "Username: admin\nPassword: nfsyg9yehhp9bt9x\nHost: server01")
    _seed_chunk(db_session, ws, sess, "other.txt",
                "Completely unrelated content about routing tables.")

    results = knowledge._query_chunks_by_keyword(
        db_session, "nfsyg9yehhp9bt9x",
        workspace_id=ws.id, session_id=sess.id, top_k=5,
    )
    assert len(results) == 1
    assert "nfsyg9yehhp9bt9x" in results[0].content


def test_keyword_search_handles_multi_word_query(db_session):
    """websearch_to_tsquery AND's the terms by default."""
    ws = _seed_workspace(db_session, "kw-multi")
    sess = _seed_session(db_session, ws.id, "kw-multi")
    _seed_chunk(db_session, ws, sess, "a.txt", "Username: admin Password: secret")
    _seed_chunk(db_session, ws, sess, "b.txt", "Just talks about password rotation policy")

    results = knowledge._query_chunks_by_keyword(
        db_session, "admin password",
        workspace_id=ws.id, session_id=sess.id, top_k=5,
    )
    contents = [r.content for r in results]
    assert any("Username: admin" in c for c in contents)


def test_keyword_search_empty_query_returns_empty(db_session):
    ws = _seed_workspace(db_session, "kw-empty")
    sess = _seed_session(db_session, ws.id, "kw-empty")
    _seed_chunk(db_session, ws, sess, "a.txt", "Some content")
    assert knowledge._query_chunks_by_keyword(
        db_session, "", workspace_id=ws.id, session_id=sess.id,
    ) == []
    assert knowledge._query_chunks_by_keyword(
        db_session, "   ", workspace_id=ws.id, session_id=sess.id,
    ) == []


def test_keyword_search_respects_session_scope(db_session):
    """A chunk in session A must not surface for a session-B query
    unless its document is is_global=True."""
    ws = _seed_workspace(db_session, "kw-scope")
    sess_a = _seed_session(db_session, ws.id, "kw-scope-a")
    sess_b = _seed_session(db_session, ws.id, "kw-scope-b")
    _seed_chunk(db_session, ws, sess_a, "private.txt",
                "Secret password: zzzunique999")

    results_a = knowledge._query_chunks_by_keyword(
        db_session, "zzzunique999",
        workspace_id=ws.id, session_id=sess_a.id, top_k=5,
    )
    results_b = knowledge._query_chunks_by_keyword(
        db_session, "zzzunique999",
        workspace_id=ws.id, session_id=sess_b.id, top_k=5,
    )
    assert len(results_a) == 1
    assert len(results_b) == 0


# ---------------------------------------------------------------------------
# RRF merge
# ---------------------------------------------------------------------------

class _StubChunk:
    """Tiny stand-in so we can test the RRF math without DB setup."""
    def __init__(self, _id: str):
        self.id = _id


def test_rrf_merge_boosts_chunks_in_both_lists():
    """A chunk appearing in BOTH lists should rank higher than chunks
    appearing in only one."""
    c1, c2, c3 = _StubChunk("c1"), _StubChunk("c2"), _StubChunk("c3")
    vector = [c1, c2, c3]
    keyword = [c2, c1]

    merged = knowledge._rrf_merge(vector, keyword, top_k=3)
    assert {c.id for c in merged[:2]} == {"c1", "c2"}
    assert merged[2].id == "c3"


def test_rrf_merge_handles_disjoint_lists():
    c1, c2, c3 = _StubChunk("c1"), _StubChunk("c2"), _StubChunk("c3")
    merged = knowledge._rrf_merge([c1], [c2, c3], top_k=3)
    assert {c.id for c in merged} == {"c1", "c2", "c3"}


def test_rrf_merge_handles_empty_lists():
    c1 = _StubChunk("c1")
    assert [c.id for c in knowledge._rrf_merge([c1], [], top_k=3)] == ["c1"]
    assert [c.id for c in knowledge._rrf_merge([], [c1], top_k=3)] == ["c1"]
    assert knowledge._rrf_merge([], [], top_k=3) == []


# ---------------------------------------------------------------------------
# End-to-end hybrid path
# ---------------------------------------------------------------------------

def test_hybrid_finds_chunk_via_keyword_when_vector_blurs(db_session):
    """The flagship case: user asks for a specific identifier the vector
    side can't reliably pick out. Keyword side rescues it; hybrid
    returns it in the top-K."""
    ws = _seed_workspace(db_session, "hybrid-id")
    sess = _seed_session(db_session, ws.id, "hybrid-id")
    target = _seed_chunk(db_session, ws, sess, "creds.txt",
                         "Server credentials: nfsyg9yehhp9bt9x stored 2026-01-01")
    for i in range(3):
        _seed_chunk(db_session, ws, sess, f"distractor{i}.txt",
                    f"Distractor content {i} talking about routing")

    results = knowledge._query_chunks_hybrid(
        db_session, query_vector=[0.5] * 768, query="nfsyg9yehhp9bt9x",
        workspace_id=ws.id, session_id=sess.id, top_k=3,
    )
    assert target.id in [r.id for r in results]


def test_hybrid_falls_back_to_vector_when_keyword_empty(db_session):
    """A conversational query ('what's the status') tokenizes to common
    words that won't match anything specific. Vector side carries it."""
    ws = _seed_workspace(db_session, "hybrid-conv")
    sess = _seed_session(db_session, ws.id, "hybrid-conv")
    target = _seed_chunk(db_session, ws, sess, "status.txt",
                         "Server status report: all green",
                         embedding=[0.5] * 768)

    results = knowledge._query_chunks_hybrid(
        db_session, query_vector=[0.5] * 768,
        query="zzzz_nonexistent_unique_string_xyz123",
        workspace_id=ws.id, session_id=sess.id, top_k=3,
    )
    # Keyword finds nothing; vector returns the seeded chunk because
    # its embedding matches the query vector exactly.
    assert target.id in [r.id for r in results]
