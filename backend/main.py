import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from config import settings
from db import database
from routers import health, chat, workspaces
from core.auth import require_token
from services.tasks import garbage_collection_task


class RequestLogger:
    """Pure ASGI middleware that prints METHOD path status duration_ms per
    request. Metadata only — no bodies, no query strings, since prompts can
    be private. /health is suppressed to keep the dev log readable.

    Implemented as a raw ASGI middleware (not a BaseHTTPMiddleware /
    @app.middleware("http") wrapper) because BaseHTTPMiddleware intercepts
    the ASGI receive channel, which silently breaks
    Request.is_disconnected() for streaming endpoints — meaning the abort
    detection in /analyze would never fire.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope["path"]
            if path != "/health":
                duration_ms = (time.perf_counter() - start) * 1000
                print(
                    f"{scope['method']} {path} {status_holder['code']} {duration_ms:.1f}ms",
                    flush=True,
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    database.init_db()
    gc_task = asyncio.create_task(garbage_collection_task())

    # Shared httpx client — one connection pool for the process lifetime.
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.LLM_CONNECT_TIMEOUT_SECONDS,
            read=settings.LLM_TIMEOUT_SECONDS,
            write=10.0,
            pool=5.0,
        ),
    )

    try:
        yield
    finally:
        await app.state.http_client.aclose()
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
app.add_middleware(RequestLogger)


app.include_router(health.router)
app.include_router(workspaces.router, dependencies=[Depends(require_token)])
app.include_router(chat.router, dependencies=[Depends(require_token)])