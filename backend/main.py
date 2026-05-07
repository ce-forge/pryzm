from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from db import database
from routers import health, chat

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

database.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)