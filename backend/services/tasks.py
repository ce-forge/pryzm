import asyncio
from datetime import datetime, timedelta, timezone
from db import database, models

async def garbage_collection_task():
    """Background task to clear orphaned documents from the loading bay."""
    while True:
        try:
            db = database.SessionLocal()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            
            deleted_count = db.query(models.Document).filter(
                models.Document.session_id == None,
                models.Document.is_global == False,
                models.Document.created_at < cutoff
            ).delete(synchronize_session=False)
            
            db.commit()
            if deleted_count > 0:
                print(f"[Garbage Collector] Purged {deleted_count} orphaned documents from loading bay.")
                
        except Exception as e:
            print(f"[Garbage Collector] Error: {e}")
        finally:
            db.close()
            
        await asyncio.sleep(3600) # Sleep for 1 hour