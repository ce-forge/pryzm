import os
import requests
import redis
from alembic import command
from alembic.config import Config
from config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("DATABASE_URL is missing in Settings! Check config.py and .env.")

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Resolve alembic.ini once at import time so we don't recompute the path on
# every startup or migration call.
_ALEMBIC_INI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic.ini",
)


def init_db():
    """Apply any pending alembic migrations before the app accepts traffic.

    Schema is owned entirely by alembic (see backend/alembic/versions/). The
    baseline migration creates the pgvector extension and all tables; future
    changes go through `alembic revision --autogenerate -m "..."`.
    """
    cfg = Config(_ALEMBIC_INI)
    command.upgrade(cfg, "head")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ping_postgres():
    try:
        with engine.connect() as connection:
            return "connected"
    except Exception as e:
        return f"disconnected: {e}"

def ping_redis():
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1)
        r.ping()
        return "connected"
    except Exception as e:
        return "disconnected"

def ping_llm_server():
    """Ping the LLM server's health endpoint. llama-swap responds 200 to GET /
    once at least one upstream llama-server has loaded."""
    try:
        response = requests.get(f"{settings.LLM_SERVER_URL.strip().rstrip('/')}/", timeout=2)
        if response.status_code == 200:
            return "connected"
        return "disconnected"
    except Exception:
        return "disconnected"