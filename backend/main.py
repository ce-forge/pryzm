import asyncio
import logging
import pathlib
import time
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from config import settings
from db import database
from routers import health, chat, workspaces, admin
from core.auth import require_token
from core import llm_router
from services import model_prewarm
from services.tasks import garbage_collection_task

# llama-swap config lives at the repo root (one level above backend/).
_LLAMA_SWAP_CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "infra" / "llama-swap-config.yaml"

# Surface llm.metric / llm.route / llm.escalate INFO lines to stdout. The
# pryzm.llm logger had no handler attached, so Phase A's metric emissions
# (and now B2's routing lines) were dropped silently. Phase C's perf-
# comparison harness greps these lines from the backend log; this makes them
# actually appear there.
_pryzm_llm_logger = logging.getLogger("pryzm.llm")
if not _pryzm_llm_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    _pryzm_llm_logger.addHandler(_handler)
    _pryzm_llm_logger.setLevel(logging.INFO)
    _pryzm_llm_logger.propagate = False


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

    catalog = llm_router.build_catalog_from_yaml(_LLAMA_SWAP_CONFIG_PATH)
    llm_router.init_router(catalog)

    # Pre-warm always-on models in the background. The server is ready
    # for traffic immediately; the warmup completes in ~10-30s. Without
    # this the first user request after a restart pays the cold-load
    # cost (and llama-swap's `persistent: true` doesn't help — it
    # prevents eviction, not initial load).
    always_on = llm_router.always_on_models_from_yaml(_LLAMA_SWAP_CONFIG_PATH)
    prewarm_task = asyncio.create_task(
        model_prewarm.warm_always_on(
            app.state.http_client, settings.LLM_SERVER_URL, always_on,
        )
    )

    try:
        yield
    finally:
        # Cancel the warmup if it's still running. We don't wait on it —
        # if it hasn't finished by shutdown time, the user wasn't going
        # to see the benefit anyway.
        prewarm_task.cancel()
        await app.state.http_client.aclose()
        # Shutdown
        gc_task.cancel()


app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Also accept any RFC1918 private-network origin on any port. This
    # makes mobile / LAN access work without forcing users to enumerate
    # the host's IP in CORS_ORIGINS. The boundary stays inside the local
    # network (no public-internet wildcards), preserving the explicit-
    # allowlist principle for non-private origins. Pair this with the
    # frontend's runtime API_URL resolution in src/utils/constants.ts.
    allow_origin_regex=settings.CORS_PRIVATE_NETWORK_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogger)


app.include_router(health.router)
app.include_router(workspaces.router, dependencies=[Depends(require_token)])
app.include_router(chat.router, dependencies=[Depends(require_token)])
app.include_router(admin.router, dependencies=[Depends(require_token)])