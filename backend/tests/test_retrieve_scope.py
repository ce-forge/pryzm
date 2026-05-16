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


@pytest.mark.asyncio
async def test_restrict_to_filenames_returns_all_chunks_not_capped(db_session):
    """When the user attaches a multi-chunk file, ALL its chunks come back —
    the previous LIMIT max(top_k*4, 8) capped at 12 even for 44-chunk files,
    which silently truncated transcription/summary requests. With the cap
    gone the model gets the whole document (subject to ctx limit at request
    time, which now surfaces the upstream error message clearly)."""
    import uuid_utils
    ws = models.Workspace(
        id="ws-allchunks", slug="ac", display_name="A",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-allchunks", workspace_id="ws-allchunks", title="t")
    doc = models.Document(
        id="doc-allchunks", filename="big.md", workspace_id="ws-allchunks",
        session_id="sess-allchunks", is_global=False,
    )
    db_session.add_all([ws, sess, doc])
    db_session.commit()

    # Seed 20 chunks with time-ordered ids
    for i in range(20):
        db_session.add(models.DocumentChunk(
            id=str(uuid_utils.uuid7()),
            document_id="doc-allchunks", workspace_id="ws-allchunks",
            content=f"chunk-body-{i:02d}", embedding=[0.1] * 768,
        ))
    db_session.commit()

    async with httpx.AsyncClient() as client:
        result = await knowledge.retrieve_relevant_chunks(
            client=client, db=db_session, query="",
            workspace_id="ws-allchunks", session_id="sess-allchunks",
            restrict_to_filenames=["big.md"],
        )
    # All 20 chunks present in the returned context, not just the first 12.
    for i in range(20):
        assert f"chunk-body-{i:02d}" in result["context"], (
            f"chunk {i} missing — retrieval is still capped"
        )


@pytest.mark.asyncio
async def test_restrict_to_filenames_preserves_chunk_insertion_order(db_session):
    """With UUIDv7 ids on chunks and ORDER BY id, retrieval gives chunks
    back in the order they were inserted — required for transcription/
    sequential reading. Random-ordered ids (v4) would scramble a transcript."""
    import uuid_utils, time
    ws = models.Workspace(
        id="ws-order", slug="ord", display_name="O",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-order", workspace_id="ws-order", title="t")
    doc = models.Document(
        id="doc-order", filename="ordered.md", workspace_id="ws-order",
        session_id="sess-order", is_global=False,
    )
    db_session.add_all([ws, sess, doc])
    db_session.commit()

    # Stagger chunk creation so UUIDv7 ids land in monotonically-increasing
    # order. 1ms apart is more than enough (v7 timestamp is millisecond-precise).
    expected_order: list[str] = []
    for i in range(8):
        chunk_id = str(uuid_utils.uuid7())
        body = f"part-{i}"
        expected_order.append(body)
        db_session.add(models.DocumentChunk(
            id=chunk_id, document_id="doc-order", workspace_id="ws-order",
            content=body, embedding=[0.1] * 768,
        ))
        time.sleep(0.002)
    db_session.commit()

    async with httpx.AsyncClient() as client:
        result = await knowledge.retrieve_relevant_chunks(
            client=client, db=db_session, query="",
            workspace_id="ws-order", session_id="sess-order",
            restrict_to_filenames=["ordered.md"],
        )
    # Verify each chunk appears in the same order it was inserted by
    # scanning the rendered context for each body in sequence.
    context = result["context"]
    positions = [context.find(body) for body in expected_order]
    assert all(p >= 0 for p in positions), f"missing chunks: {positions}"
    assert positions == sorted(positions), (
        f"chunks out of order — got positions {positions}"
    )


@pytest.mark.asyncio
async def test_add_chunks_to_document_uses_time_ordered_ids(db_session, monkeypatch):
    """New chunks created via the ingest pipeline get UUIDv7 ids so they
    sort lexicographically into insertion order. Regression: chunks used
    to get random UUIDv4 ids, which made ORDER BY id useless."""
    from services import knowledge as knowledge_mod
    ws = models.Workspace(
        id="ws-v7", slug="v7", display_name="V",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-v7", workspace_id="ws-v7", title="t")
    doc = models.Document(
        id="doc-v7", filename="seq.md", workspace_id="ws-v7",
        session_id="sess-v7", is_global=False,
    )
    db_session.add_all([ws, sess, doc])
    db_session.commit()

    async def fake_embed(_client, _text):
        return [0.0] * 768
    monkeypatch.setattr(knowledge_mod, "get_embedding", fake_embed)

    # Content long enough to produce >= 4 chunks given chunk_size=1000.
    content = "\n\n".join([f"section {i}: " + ("x " * 600) for i in range(6)])
    async with httpx.AsyncClient() as client:
        n = await knowledge_mod.add_chunks_to_document(client, db_session, doc, content)
    assert n >= 4

    chunks = (
        db_session.query(models.DocumentChunk)
        .filter(models.DocumentChunk.document_id == "doc-v7")
        .all()
    )
    ids_in_db_order = [c.id for c in chunks]
    # UUIDv7 starts with a 48-bit timestamp; lexicographic sort = insertion order
    # for chunks created back-to-back in this loop.
    assert ids_in_db_order == sorted(ids_in_db_order), (
        f"chunk ids are not time-ordered: {ids_in_db_order}"
    )
