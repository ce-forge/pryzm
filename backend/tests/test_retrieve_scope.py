"""Retrieval-scope tests for the auto-RAG branch in
services/knowledge.retrieve_relevant_chunks.

When the user attaches a file the auto-RAG path scopes retrieval to
that specific document (restrict_to_filenames) instead of running a
workspace-wide semantic search. These tests pin that behavior. The
previous file (test_reattach.py) also exercised image re-attach
plumbing; that path was dropped — captions are now the sole record
of image content — and the corresponding tests went with it.
"""
from __future__ import annotations

import httpx
import pytest

from db import models
from services import knowledge


@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_scopes_to_attached_filename(
    db_session, tmp_path,
):
    """When restrict_to_filenames is set, retrieval pins to documents
    whose filename matches AND ignores other docs even if they'd
    otherwise match the scope filter. Regression: user attaches
    images.jpeg and asks 'what is this?' — only images.jpeg chunks
    come back, not all global docs in the workspace."""
    ws = models.Workspace(
        id="ws-scoped",
        slug="scoped",
        display_name="S",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-scoped", workspace_id="ws-scoped", title="t")

    target_doc = models.Document(
        id="doc-target", filename="target.png", workspace_id="ws-scoped",
        session_id="sess-scoped", is_global=False,
    )
    distractor_doc = models.Document(
        id="doc-distractor", filename="distractor.png", workspace_id="ws-scoped",
        session_id=None, is_global=True,
    )
    target_chunk = models.DocumentChunk(
        id="chunk-target", document_id="doc-target", workspace_id="ws-scoped",
        content="This is the attached image's caption.", embedding=[0.1] * 768,
    )
    distractor_chunk = models.DocumentChunk(
        id="chunk-distractor", document_id="doc-distractor", workspace_id="ws-scoped",
        content="Caption for a totally unrelated image.", embedding=[0.1] * 768,
    )
    db_session.add_all([ws, sess, target_doc, distractor_doc, target_chunk, distractor_chunk])
    db_session.commit()

    async with httpx.AsyncClient() as client:
        result = await knowledge.retrieve_relevant_chunks(
            client=client, db=db_session, query="what is this?",
            workspace_id="ws-scoped", session_id="sess-scoped",
            restrict_to_filenames=["target.png"],
        )
    assert result is not None
    assert result["sources"] == ["target.png"]
    assert "distractor" not in result["context"]


@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_falls_back_when_attached_filename_missing(
    db_session,
):
    """If the attached filename doesn't match any doc (file was
    deleted, marker is stale), retrieval falls through to the broader
    paths instead of returning nothing — the chat shouldn't dead-end."""
    ws = models.Workspace(
        id="ws-fallback", slug="fallback", display_name="F",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-fallback", workspace_id="ws-fallback", title="t")
    doc = models.Document(
        id="doc-fallback", filename="exists.txt", workspace_id="ws-fallback",
        session_id="sess-fallback", is_global=False,
    )
    chunk = models.DocumentChunk(
        id="chunk-fallback", document_id="doc-fallback", workspace_id="ws-fallback",
        content="Some text.", embedding=[0.1] * 768,
    )
    db_session.add_all([ws, sess, doc, chunk])
    db_session.commit()

    async with httpx.AsyncClient() as client:
        result = await knowledge.retrieve_relevant_chunks(
            client=client, db=db_session, query="",
            workspace_id="ws-fallback", session_id="sess-fallback",
            overview_mode=True,
            restrict_to_filenames=["gone.png"],
        )
    assert result is not None
    assert "exists.txt" in result["sources"]
