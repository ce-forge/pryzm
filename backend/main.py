import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from db import database
from routers import health, chat
from services.tasks import garbage_collection_task

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    database.init_db()
    gc_task = asyncio.create_task(garbage_collection_task())
    
    yield
    
    # Shutdown
    gc_task.cancel()

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)