import requests
import redis
from config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base


SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("DATABASE_URL is missing in Settings! Check config.py and .env.")

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    with engine.connect() as conn:
        conn.execute(text("Create EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
    Base.metadata.create_all(bind=engine)

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
        r = redis.Redis(host='localhost', port=6379, db=0, socket_timeout=1)
        r.ping()
        return "connected"
    except Exception as e:
        return "disconnected"

def ping_ollama():
    try:
        response = requests.get("http://localhost:11434/", timeout=2)
        if response.status_code == 200:
            return "connected"
        return "disconnected"
    except Exception:
        return "disconnected"