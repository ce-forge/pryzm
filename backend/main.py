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
from routers import health, chat, workspaces, admin, folders, documents
from routers import settings as settings_router
from routers import auth as auth_router
from routers import admin_users as admin_users_router
from routers import admin_templates as admin_templates_router
from routers import admin_workspaces as admin_workspaces_router
from routers import admin_audit as admin_audit_router
from routers import admin_engine as admin_engine_router
from routers import admin_sessions as admin_sessions_router
from routers import bug_reports as bug_reports_router
from routers import notifications as notifications_router
from core import cookie_auth, llm_router
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

# Same shape for `services.*` so diagnostic INFO logs from ocr_extract,
# image_describe, model_prewarm, etc. surface in the dev terminal.
# uvicorn's default config only wires uvicorn.* at INFO; everything else
# inherits root WARNING and gets silently dropped.
# Note: we leave propagate=True so pytest's caplog (which captures from
# root) still works for tests that import this module transitively.
_services_logger = logging.getLogger("services")
if not _services_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    _services_logger.addHandler(_handler)
    _services_logger.setLevel(logging.INFO)


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

    # Bootstrap admin on first boot. If users table is empty and the env var
    # isn't set, this raises and startup fails — by design, points the operator
    # at the missing env var.
    from db import database as _db
    from core.bootstrap import ensure_bootstrap_admin
    _bootstrap_db = _db.SessionLocal()
    try:
        ensure_bootstrap_admin(_bootstrap_db)
    finally:
        _bootstrap_db.close()

    gc_task = asyncio.create_task(garbage_collection_task())

    # Audit-events partition lifecycle: ensure next month is provisioned
    # and drop partitions outside the retention window. Runs immediately
    # then once a day.
    from services.audit_retention_scheduler import audit_retention_loop
    audit_retention_task = asyncio.create_task(audit_retention_loop())

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

    # Pre-warm always-on + vision-tagged models in the background. The
    # server is ready for traffic immediately; warmup completes in
    # ~10-30s. Without this, first user request pays cold-load cost
    # (llama-swap's `persistent: true` prevents eviction, not initial
    # load), and first image upload pays it on the VLM specifically.
    models = llm_router.models_to_prewarm_from_yaml(_LLAMA_SWAP_CONFIG_PATH)
    prewarm_task = asyncio.create_task(
        model_prewarm.warm_models(
            app.state.http_client, settings.LLM_SERVER_URL, models,
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
        audit_retention_task.cancel()


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
app.include_router(auth_router.router)
app.include_router(workspaces.router, dependencies=[Depends(cookie_auth.current_user)])
app.include_router(chat.router, dependencies=[Depends(cookie_auth.current_user)])
app.include_router(folders.router, dependencies=[Depends(cookie_auth.current_user)])
app.include_router(documents.router, dependencies=[Depends(cookie_auth.current_user)])
app.include_router(settings_router.router, dependencies=[Depends(cookie_auth.require_admin)])
app.include_router(admin.router, dependencies=[Depends(cookie_auth.require_admin)])
app.include_router(admin_users_router.router)
app.include_router(admin_templates_router.router)
app.include_router(admin_workspaces_router.router)
app.include_router(admin_audit_router.router)
app.include_router(admin_engine_router.router)
app.include_router(admin_sessions_router.router)
app.include_router(bug_reports_router.user_router)
app.include_router(bug_reports_router.admin_router)
app.include_router(notifications_router.user_router)
app.include_router(notifications_router.admin_router)