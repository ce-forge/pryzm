"""Tests for filename-mention auto-RAG and the filenames-aware
`search_knowledge_base` tool. Both paths exist so the LLM can pick
up references to previously-uploaded files in a follow-up turn
without the user having to re-attach."""
from __future__ import annotations

import pytest

from core import ai_engine
from db import models
from services import knowledge
from tools.retrieval import search_knowledge_base


def _seed_workspace(db, slug="fnmention"):
    user = models.User(
        id=f"user-{slug}", username=slug, password_hash="hash", is_admin=False
    )
    ws = models.Workspace(
        id=f"ws-{slug}",
        slug=slug,
        display_name="FN Test",
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        user_id=f"user-{slug}",
    )
    db.add(user); db.commit()
    db.add(ws); db.commit(); return ws


def _seed_session(db, ws_id, slug="session-fn"):
    # Extract user_id from workspace
    ws = db.query(models.Workspace).filter_by(id=ws_id).one()
    s = models.Session(id=f"sess-{slug}", title="t", workspace_id=ws_id, user_id=ws.user_id)
    db.add(s); db.commit(); return s


def _seed_document_with_chunk(db, ws, session, filename, content):
    doc = models.Document(filename=filename, workspace_id=ws.id, session_id=session.id)
    db.add(doc); db.commit(); db.refresh(doc)
    chunk = models.DocumentChunk(
        document_id=doc.id,
        workspace_id=ws.id,
        content=content,
        embedding=[0.1] * 768,
    )
    db.add(chunk); db.commit()
    return doc


# ---------------------------------------------------------------------------
# ai_engine._match_session_filename_mentions
# ---------------------------------------------------------------------------

def _patch_session_local_to_test_db(monkeypatch, db_session):
    """Wire ai_engine's `database.SessionLocal()` to the test session."""
    from sqlalchemy.orm import sessionmaker
    from db import database
    test_engine = db_session.get_bind()
    TestLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", TestLocal)


def test_filename_mention_matches_session_document(db_session, monkeypatch):
    ws = _seed_workspace(db_session, "match-yes")
    sess = _seed_session(db_session, ws.id, "match-yes")
    _seed_document_with_chunk(db_session, ws, sess, "screenshot.png", "irrelevant body")
    _patch_session_local_to_test_db(monkeypatch, db_session)

    matched = ai_engine._match_session_filename_mentions(
        "what was the IP in screenshot.png?",
        workspace_id=ws.id, session_id=sess.id,
    )
    assert matched == ["screenshot.png"]


def test_filename_mention_case_insensitive(db_session, monkeypatch):
    """User capitalizes the filename in casual text — still matches."""
    ws = _seed_workspace(db_session, "match-case")
    sess = _seed_session(db_session, ws.id, "match-case")
    _seed_document_with_chunk(db_session, ws, sess, "screenshot.png", "body")
    _patch_session_local_to_test_db(monkeypatch, db_session)

    matched = ai_engine._match_session_filename_mentions(
        "Show me Screenshot.PNG",
        workspace_id=ws.id, session_id=sess.id,
    )
    assert matched == ["screenshot.png"]


def test_filename_mention_no_match_returns_empty(db_session, monkeypatch):
    ws = _seed_workspace(db_session, "match-no")
    sess = _seed_session(db_session, ws.id, "match-no")
    _seed_document_with_chunk(db_session, ws, sess, "actual.png", "body")
    _patch_session_local_to_test_db(monkeypatch, db_session)

    matched = ai_engine._match_session_filename_mentions(
        "what's in nope.png?",
        workspace_id=ws.id, session_id=sess.id,
    )
    assert matched == []


def test_filename_mention_only_matches_session_scope(db_session, monkeypatch):
    """A document in workspace W1 session S1 must not match when the
    query is in W1 session S2 — cross-session leakage would surface
    unrelated docs."""
    ws = _seed_workspace(db_session, "match-scope")
    s1 = _seed_session(db_session, ws.id, "match-scope-1")
    s2 = _seed_session(db_session, ws.id, "match-scope-2")
    _seed_document_with_chunk(db_session, ws, s1, "private.png", "body")
    _patch_session_local_to_test_db(monkeypatch, db_session)

    matched = ai_engine._match_session_filename_mentions(
        "show me private.png",
        workspace_id=ws.id, session_id=s2.id,
    )
    assert matched == []


def test_filename_mention_includes_global_docs(db_session, monkeypatch):
    """is_global=True documents are visible from any session in the workspace."""
    ws = _seed_workspace(db_session, "match-global")
    sess = _seed_session(db_session, ws.id, "match-global-sess")
    glob_doc = models.Document(
        filename="runbook.pdf",
        workspace_id=ws.id,
        is_global=True,
    )
    db_session.add(glob_doc); db_session.commit()
    _patch_session_local_to_test_db(monkeypatch, db_session)

    matched = ai_engine._match_session_filename_mentions(
        "what does runbook.pdf say?",
        workspace_id=ws.id, session_id=sess.id,
    )
    assert matched == ["runbook.pdf"]


def test_filename_mention_ignores_non_filename_tokens(db_session, monkeypatch):
    """Version strings like '1.5.2' or partial words shouldn't trigger
    filename matching. Pattern is constrained to extensions we ingest."""
    ws = _seed_workspace(db_session, "match-noise")
    sess = _seed_session(db_session, ws.id, "match-noise-sess")
    _patch_session_local_to_test_db(monkeypatch, db_session)

    matched = ai_engine._match_session_filename_mentions(
        "running v1.5.2 with config.gz and other.xyz files",
        workspace_id=ws.id, session_id=sess.id,
    )
    # None of these are extensions in our pattern OR session docs.
    assert matched == []


# ---------------------------------------------------------------------------
# search_knowledge_base tool with `filenames`
# ---------------------------------------------------------------------------

class _StubChunk:
    def __init__(self, content, filename):
        self.content = content
        class _Doc: pass
        self.document = _Doc()
        self.document.filename = filename


def test_search_tool_passes_filenames_through(monkeypatch):
    captured: dict = {}

    def fake_search(db, query, *, workspace_id, session_id, threshold, top_k, restrict_to_filenames):
        captured["filenames"] = restrict_to_filenames
        captured["query"] = query
        return [_StubChunk("found content", "target.pdf")]

    monkeypatch.setattr("tools.retrieval.search_chunks_sync", fake_search)
    monkeypatch.setattr("tools.retrieval.SessionLocal", lambda: _DummyDb())

    out, _audit = search_knowledge_base(
        queries=["the IP"],
        workspace_id="ws-1",
        session_id="sess-1",
        filenames=["target.pdf"],
    )
    assert captured["filenames"] == ["target.pdf"]
    assert "found content" in out


def test_search_tool_filenames_none_when_omitted(monkeypatch):
    captured: dict = {}

    def fake_search(db, query, *, workspace_id, session_id, threshold, top_k, restrict_to_filenames):
        captured["filenames"] = restrict_to_filenames
        return []

    monkeypatch.setattr("tools.retrieval.search_chunks_sync", fake_search)
    monkeypatch.setattr("tools.retrieval.SessionLocal", lambda: _DummyDb())

    search_knowledge_base(queries=["the IP"], workspace_id="ws-1", session_id="sess-1")
    assert captured["filenames"] is None


def test_search_tool_accepts_bare_string_filenames(monkeypatch):
    """A model that returns `filenames` as a string (not array) shouldn't
    crash — wrap in a list."""
    captured: dict = {}

    def fake_search(db, query, *, workspace_id, session_id, threshold, top_k, restrict_to_filenames):
        captured["filenames"] = restrict_to_filenames
        return []

    monkeypatch.setattr("tools.retrieval.search_chunks_sync", fake_search)
    monkeypatch.setattr("tools.retrieval.SessionLocal", lambda: _DummyDb())

    search_knowledge_base(
        queries=["q"], workspace_id="ws-1", session_id="sess-1",
        filenames="single.png",
    )
    assert captured["filenames"] == ["single.png"]


class _DummyDb:
    def close(self): pass
