import asyncio
from datetime import datetime, timedelta, timezone
from db import database, models


def _gc_pass(db) -> int:
    """Run one garbage-collection pass. Returns the number of rows deleted.

    Uses ORM-style iteration so SQLAlchemy's after_delete hook on Document
    fires per row and removes the file on disk via storage_path.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    docs = db.query(models.Document).filter(
        models.Document.session_id == None,
        models.Document.is_global == False,
        models.Document.created_at < cutoff,
    ).all()
    for d in docs:
        db.delete(d)
    db.commit()
    return len(docs)


async def garbage_collection_task():
    """Background task: hourly sweep of orphaned documents in the loading bay."""
    while True:
        db = None
        try:
            db = database.SessionLocal()
            deleted = _gc_pass(db)
            if deleted > 0:
                print(f"[Garbage Collector] Purged {deleted} orphaned documents.")
        except Exception as e:
            print(f"[Garbage Collector] Error: {e}")
        finally:
            if db is not None:
                db.close()
        await asyncio.sleep(3600)
