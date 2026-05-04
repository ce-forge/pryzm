from fastapi import APIRouter
from pydantic import BaseModel
import database

router = APIRouter(tags=["System Health"])

class SystemStatus(BaseModel):
    api: str
    redis: str
    database: str
    inference_engine: str

class HealthResponse(BaseModel):
    status: str
    components: SystemStatus

@router.get("/health", response_model=HealthResponse)
def get_health(): # Removed 'async' to prevent blocking!
    pg_status = database.ping_postgres()
    redis_status = database.ping_redis()
    ollama_status = database.ping_ollama()

    overall_status = "online"
    if "disconnected" in pg_status or "disconnected" in redis_status:
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        components=SystemStatus(
            api="healthy",
            redis=redis_status,
            database=pg_status,
            inference_engine=ollama_status
        )
    )