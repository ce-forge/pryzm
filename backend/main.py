from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
import database

from routers import health, chat

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

origins =[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.0.108:3000",
    "http://192.168.0.108"
]

database.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)