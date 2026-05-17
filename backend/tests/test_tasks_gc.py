"""GC sweep must trigger the after_delete hook so image files are removed."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

from db import models
from services import tasks


def test_gc_removes_orphan_document_and_its_storage_file(db_session):
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    assert os.path.exists(path)

    ws = models.Workspace(
        id="ws-gc", slug="ws-gc", display_name="GC",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    cutoff_old = datetime.now(timezone.utc) - timedelta(hours=48)
    doc = models.Document(
        id="doc-gc", workspace_id="ws-gc", session_id=None,
        is_global=False, filename="x.png",
        status="ready", storage_path=path, created_at=cutoff_old,
    )
    db_session.add_all([ws, doc])
    db_session.commit()

    deleted = tasks._gc_pass(db_session)
    assert deleted == 1
    assert not os.path.exists(path), f"GC should have removed {path}"
    assert db_session.query(models.Document).filter_by(id="doc-gc").first() is None
