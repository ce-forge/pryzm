"""Unit + integration tests for VLM Milestone 3: re-attach original
images to the LLM call when RAG selects an image-derived chunk.

Three layers covered:
  - services.image_storage.read_as_data_url (file → data URL helper)
  - core.llm_router.HeuristicRouter.vision_capable (catalog lookup)
  - services.knowledge.retrieve_relevant_chunks surfaces reattach_images
"""
from __future__ import annotations

import os

import httpx
import pytest

from core import llm_server
from core.llm_router import HeuristicRouter
from db import models
from services import image_storage, knowledge


# ---------------------------------------------------------------------------
# image_storage.read_as_data_url
# ---------------------------------------------------------------------------

def test_read_as_data_url_returns_base64_for_real_file(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"raw-png-bytes")
    out = image_storage.read_as_data_url(str(p))
    assert out is not None
    assert out.startswith("data:image/png;base64,")
    encoded = out.split(",", 1)[1]
    import base64
    assert base64.b64decode(encoded) == b"raw-png-bytes"


def test_read_as_data_url_returns_none_for_missing_file(tmp_path):
    assert image_storage.read_as_data_url(str(tmp_path / "nope.png")) is None


def test_read_as_data_url_returns_none_for_unsupported_extension(tmp_path):
    p = tmp_path / "doc.tiff"
    p.write_bytes(b"x")
    assert image_storage.read_as_data_url(str(p)) is None


def test_read_as_data_url_returns_none_for_empty_path():
    assert image_storage.read_as_data_url("") is None
    assert image_storage.read_as_data_url(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HeuristicRouter.vision_capable
# ---------------------------------------------------------------------------

def test_vision_capable_true_when_model_has_vision_tag():
    r = HeuristicRouter({
        "mini-2b": {"vision"},
        "big-4b": {"vision"},
    })
    assert r.vision_capable("mini-2b") is True
    assert r.vision_capable("big-4b") is True


def test_vision_capable_false_when_tag_absent():
    r = HeuristicRouter({
        "mini-2b": set(),
        "big-4b": set(),
    })
    assert r.vision_capable("mini-2b") is False
    assert r.vision_capable("big-4b") is False


def test_vision_capable_false_for_unknown_model():
    r = HeuristicRouter({
        "mini-2b": {"vision"},
        "big-4b": {"vision"},
    })
    assert r.vision_capable("not-in-catalog") is False


# ---------------------------------------------------------------------------
# _collect_reattach_paths
# ---------------------------------------------------------------------------

def test_collect_reattach_paths_dedupes_and_filters_missing(tmp_path):
    # Two real files, one missing path. One Document referenced twice.
    real_a = tmp_path / "a.png"; real_a.write_bytes(b"a")
    real_b = tmp_path / "b.png"; real_b.write_bytes(b"b")

    class FakeDoc:
        def __init__(self, p): self.storage_path = p

    docs = [
        FakeDoc(str(real_a)),
        FakeDoc(str(real_a)),                  # duplicate → drop
        FakeDoc(str(real_b)),
        FakeDoc(str(tmp_path / "missing.png")),  # not on disk → drop
        FakeDoc(None),                           # text doc → drop
    ]
    paths = knowledge._collect_reattach_paths(docs)
    assert paths == [str(real_a), str(real_b)]


# ---------------------------------------------------------------------------
# retrieve_relevant_chunks emits reattach_images for image-bearing docs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_emits_reattach_for_image_docs(
    db_session, monkeypatch, tmp_path
):
    """A Document with storage_path → its file shows up in the
    reattach_images list of the retrieval result."""
    ws = models.Workspace(
        id="ws-reattach",
        slug="reattach",
        display_name="R",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-reattach", workspace_id="ws-reattach", title="t")
    img_path = tmp_path / "captured.png"
    img_path.write_bytes(b"i-am-an-image")
    doc = models.Document(
        id="doc-reattach",
        filename="captured.png",
        workspace_id="ws-reattach",
        session_id="sess-reattach",
        is_global=False,
        storage_path=str(img_path),
    )
    chunk = models.DocumentChunk(
        id="chunk-reattach",
        document_id="doc-reattach",
        workspace_id="ws-reattach",
        content="A description of a captured image.",
        embedding=[0.1] * 768,
    )
    db_session.add_all([ws, sess, doc, chunk])
    db_session.commit()

    # Force the overview path (it surfaces the most recent document for
    # the session) so we don't depend on cosine-distance behavior with a
    # fixed-vector embedding.
    async with httpx.AsyncClient() as client:
        result = await knowledge.retrieve_relevant_chunks(
            client=client,
            db=db_session,
            query="",
            workspace_id="ws-reattach",
            session_id="sess-reattach",
            overview_mode=True,
        )

    assert result is not None
    assert result["sources"] == ["captured.png"]
    assert result.get("reattach_images") == [str(img_path)]


@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_scopes_to_attached_filename(
    db_session, tmp_path,
):
    """When restrict_to_filenames is set, retrieval pins to documents whose
    filename matches AND ignores other docs even if they'd otherwise match
    the scope filter. Regression: user attaches images.jpeg and asks
    'what is this?' → only images.jpeg chunks come back, not all global
    docs in the workspace."""
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

    target_path = tmp_path / "target.png"
    target_path.write_bytes(b"target")
    other_path = tmp_path / "other.png"
    other_path.write_bytes(b"other")

    target_doc = models.Document(
        id="doc-target", filename="target.png", workspace_id="ws-scoped",
        session_id="sess-scoped", is_global=False, storage_path=str(target_path),
    )
    # Global doc that the OLD behavior would surface alongside target.
    distractor_doc = models.Document(
        id="doc-distractor", filename="distractor.png", workspace_id="ws-scoped",
        session_id=None, is_global=True, storage_path=str(other_path),
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
    assert result["reattach_images"] == [str(target_path)]
    assert "distractor" not in result["context"]


@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_falls_back_when_attached_filename_missing(
    db_session,
):
    """If the attached filename doesn't match any doc (e.g., file was
    deleted), retrieval falls through to the broader paths instead of
    returning nothing — the chat shouldn't dead-end on a stale marker."""
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
        # Filename that doesn't match anything → overview_mode kicks in
        # because we also pass overview_mode=True (no user text).
        result = await knowledge.retrieve_relevant_chunks(
            client=client, db=db_session, query="",
            workspace_id="ws-fallback", session_id="sess-fallback",
            overview_mode=True,
            restrict_to_filenames=["gone.png"],
        )
    # Fallback to the overview path returns the existing doc.
    assert result is not None
    assert "exists.txt" in result["sources"]


# ---------------------------------------------------------------------------
# Tool-RAG side-channel: search_knowledge_base publishes image paths and
# ai_engine.consume_pending_image_paths drains them.
# ---------------------------------------------------------------------------

def test_consume_pending_image_paths_starts_empty():
    """Fresh context, nothing published yet → empty list."""
    knowledge.consume_pending_image_paths()  # ensure-empty
    assert knowledge.consume_pending_image_paths() == []


def test_publish_then_consume_returns_paths_and_clears(tmp_path):
    """Publish a set of image-bearing docs, then drain — second drain is empty."""
    knowledge.consume_pending_image_paths()  # clear any leftover

    a = tmp_path / "a.png"; a.write_bytes(b"a")
    b = tmp_path / "b.png"; b.write_bytes(b"b")

    class FakeDoc:
        def __init__(self, p): self.storage_path = p

    knowledge._publish_pending_image_paths([FakeDoc(str(a)), FakeDoc(str(b))])
    first = knowledge.consume_pending_image_paths()
    assert first == [str(a), str(b)]
    assert knowledge.consume_pending_image_paths() == []


def test_publish_dedupes_within_a_batch(tmp_path):
    """Same path published twice (same doc surfaced by two queries) only
    shows up once in the consumed list."""
    knowledge.consume_pending_image_paths()  # clear

    p = tmp_path / "shared.png"; p.write_bytes(b"x")

    class FakeDoc:
        def __init__(self, p): self.storage_path = p

    knowledge._publish_pending_image_paths([FakeDoc(str(p))])
    knowledge._publish_pending_image_paths([FakeDoc(str(p))])

    assert knowledge.consume_pending_image_paths() == [str(p)]


def test_search_knowledge_base_publishes_image_doc_paths(db_session, tmp_path, monkeypatch):
    """When search_knowledge_base hits chunks whose Documents have a
    storage_path, those paths land in the pending-image queue. Text-only
    docs don't publish anything."""
    from tools.retrieval import search_knowledge_base
    from db.database import SessionLocal as _SL

    knowledge.consume_pending_image_paths()

    ws = models.Workspace(
        id="ws-tool-rag", slug="tool-rag", display_name="T",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    img_path = tmp_path / "rag_target.png"; img_path.write_bytes(b"img")
    image_doc = models.Document(
        id="doc-img-tool", filename="rag_target.png", workspace_id="ws-tool-rag",
        is_global=True, storage_path=str(img_path),
    )
    text_doc = models.Document(
        id="doc-txt-tool", filename="notes.txt", workspace_id="ws-tool-rag",
        is_global=True, storage_path=None,
    )
    image_chunk = models.DocumentChunk(
        id="chk-img-tool", document_id="doc-img-tool", workspace_id="ws-tool-rag",
        content="An image of a router rack in a data center.", embedding=[0.1] * 768,
    )
    text_chunk = models.DocumentChunk(
        id="chk-txt-tool", document_id="doc-txt-tool", workspace_id="ws-tool-rag",
        content="Operating procedure for the rack.", embedding=[0.1] * 768,
    )
    db_session.add_all([ws, image_doc, text_doc, image_chunk, text_chunk])
    db_session.commit()

    # Make the tool see our test DB instead of the dev DB.
    monkeypatch.setattr("tools.retrieval.SessionLocal", lambda: db_session)
    # Bypass embedding HTTP — return a vector that will match the seeded chunks
    # via the cosine search OR the ILIKE fallback.
    monkeypatch.setattr(knowledge, "_query_chunks_by_vector",
                        lambda db, vec, q, ws_id, sess_id=None, threshold=0.45, top_k=3:
                            db.query(models.DocumentChunk)
                              .filter_by(workspace_id=ws_id).all())
    # Also short-circuit search_chunks_sync's embedding HTTP.
    import requests as _rq
    class _DummyResp:
        def raise_for_status(self): pass
        def json(self): return {"data": [{"embedding": [0.1] * 768}]}
    monkeypatch.setattr(_rq, "post", lambda *a, **kw: _DummyResp())

    result = search_knowledge_base(queries=["rack"], workspace_id="ws-tool-rag")
    assert "rack" in result.lower()

    published = knowledge.consume_pending_image_paths()
    assert published == [str(img_path)], (
        f"expected only the image doc's path; got {published!r}"
    )


@pytest.mark.asyncio
async def test_retrieve_relevant_chunks_omits_reattach_for_text_docs(
    db_session,
):
    """A Document without storage_path → reattach_images is the empty list."""
    ws = models.Workspace(
        id="ws-text",
        slug="text",
        display_name="T",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    sess = models.Session(id="sess-text", workspace_id="ws-text", title="t")
    doc = models.Document(
        id="doc-text",
        filename="notes.txt",
        workspace_id="ws-text",
        session_id="sess-text",
        is_global=False,
    )
    chunk = models.DocumentChunk(
        id="chunk-text",
        document_id="doc-text",
        workspace_id="ws-text",
        content="Just some text.",
        embedding=[0.1] * 768,
    )
    db_session.add_all([ws, sess, doc, chunk])
    db_session.commit()

    async with httpx.AsyncClient() as client:
        result = await knowledge.retrieve_relevant_chunks(
            client=client,
            db=db_session,
            query="",
            workspace_id="ws-text",
            session_id="sess-text",
            overview_mode=True,
        )
    assert result is not None
    assert result.get("reattach_images") == []
