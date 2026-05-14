from fastapi import APIRouter
from pydantic import BaseModel
from db import database
from schemas import SystemStatus, HealthResponse

router = APIRouter(tags=["System Health"])

@router.get("/health", response_model=HealthResponse)
def get_health():
    pg_status = database.ping_postgres()
    redis_status = database.ping_redis()
    ollama_status = database.ping_llm_server()

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