"""Embedding failure mid-loop must not persist partial chunks."""
import pytest

from db import models
from services import ingest_broker, ingest_pipeline, knowledge


@pytest.mark.asyncio
async def test_partial_chunks_rolled_back_on_embedding_failure(db_session, monkeypatch):
    user = models.User(
        id="user-ing", username="ing", password_hash="hash", is_admin=False
    )
    ws = models.Workspace(
        id="ws-ing", slug="ws-ing", display_name="ING",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
        user_id="user-ing",
    )
    sess = models.Session(id="sess-ing", workspace_id="ws-ing", title="t", user_id="user-ing")
    doc = models.Document(
        id="doc-ing", workspace_id="ws-ing", session_id="sess-ing",
        filename="a.txt", status="processing",
    )
    db_session.add_all([user, ws, sess, doc])
    db_session.commit()

    calls = {"n": 0}

    async def flaky_embed(_client, _text):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("ollama dropped the call")
        return [0.0] * 768

    monkeypatch.setattr(knowledge, "get_embedding", flaky_embed)

    # Content long enough that the splitter produces enough chunks to
    # exercise the flaky-embed threshold and leave partial inserts on
    # the session when the third embedding raises.
    content = "\n\n".join([f"section {i}: " + ("x " * 600) for i in range(6)])

    with pytest.raises(RuntimeError):
        await knowledge.add_chunks_to_document(
            None, db_session, doc, content,
        )

    broker = ingest_broker.IngestBroker()
    await ingest_pipeline._finalize_error(
        db_session, broker, doc, "ollama dropped the call",
    )

    remaining = db_session.query(models.DocumentChunk).filter_by(
        document_id="doc-ing",
    ).count()
    assert remaining == 0

    refreshed = db_session.query(models.Document).filter_by(id="doc-ing").one()
    assert refreshed.status == "error"
    assert refreshed.error_message == "ollama dropped the call"
