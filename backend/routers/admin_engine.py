"""Reverse proxy that exposes llama-swap's UI under /api/admin/engine/*.

The llama-swap container binds to 127.0.0.1:8080 (firewalled from
external access). We proxy through the backend so the operator only has
to expose Pryzm's port — and so llama-swap's UI inherits Pryzm's admin
auth, which it has no notion of on its own.

Implementation:
- Catch-all route for all HTTP verbs at /api/admin/engine/{path:path}.
- Forwards method, query string, request body, and a filtered header
  set to the upstream. Streams the response back so SSE endpoints
  (llama-swap's /api/events) work end-to-end.
- WebSocket upgrade NOT handled in v1 — llama-swap uses SSE for live
  data today. If a future upstream change introduces WS we'll need
  a separate WebSocketRoute.
- Caveat: llama-swap's UI may emit absolute URLs that break under the
  iframe sub-path. Listed in the dashboard spec as the main wrinkle to
  resolve if the iframe renders blank.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from config import settings
from core import cookie_auth


router = APIRouter(
    prefix="/api/admin/engine",
    tags=["admin", "engine"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


_logger = logging.getLogger(__name__)


# llama-swap's UI emits absolute paths like `/ui/foo.js` and `/api/models`
# that resolve against the iframe's origin — i.e. against Pryzm, not under
# the proxy prefix. We rewrite those to point back at the proxy. The path
# segments listed here cover everything llama-swap serves at the top level
# (UI assets, JSON API, model upstreams) — verified by grepping the
# minified bundle.
_PROXY_PREFIX = "/api/admin/engine"
_UPSTREAM_PATHS = (
    "ui", "api", "favicon",
    # UI-route segments (navigated to via SPA router)
    "models", "activity", "logs", "performance",
    # Model-server upstream paths llama-swap forwards on its end
    "upstream", "running", "sdapi", "v1",
)
# Opens with " ' ` ( — template-literal backticks are how the bundle
# constructs most fetch/EventSource URLs.
_REWRITE_PATTERN = re.compile(
    r'(["\'`(])(/(?:' + "|".join(_UPSTREAM_PATHS) + r')(?:[/?"`\'\s)]|$))'
)


def _rewrite_body(body: bytes) -> bytes:
    """Inject the proxy prefix into absolute paths inside HTML / JS / JSON
    text payloads. Conservative — only rewrites strings that start with
    `/ui/`, `/api/`, etc. matching the upstream's top-level path set."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    rewritten = _REWRITE_PATTERN.sub(
        lambda m: f"{m.group(1)}{_PROXY_PREFIX}{m.group(2)}", text,
    )
    return rewritten.encode("utf-8")


def _rewrite_location(location: str) -> str:
    """3xx Location headers from upstream are root-relative paths; prefix
    them so the browser stays inside the proxy."""
    if location.startswith("/") and not location.startswith(_PROXY_PREFIX):
        return _PROXY_PREFIX + location
    return location


_REWRITE_CONTENT_TYPES = (
    "text/html", "text/javascript", "application/javascript",
    "application/json", "text/css",
)


def _should_rewrite_body(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.split(";", 1)[0].strip().lower()
    return ct in _REWRITE_CONTENT_TYPES


# Headers we strip before forwarding to llama-swap. Host gets rewritten,
# the rest are connection-scoped and shouldn't propagate.
_HOP_BY_HOP = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    # Don't leak Pryzm's session cookie upstream — llama-swap has no auth
    # and would ignore it, but it's still a sensible posture.
    "cookie",
    # Strip auth headers too; llama-swap doesn't speak them.
    "authorization",
}


def _filter_request_headers(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


def _filter_response_headers(headers) -> list[tuple[str, str]]:
    # Drop hop-by-hop response headers; httpx already decodes
    # content-encoding so passing it through would double-decode.
    drop = _HOP_BY_HOP | {"content-encoding", "content-length"}
    return [(k, v) for k, v in headers.items() if k.lower() not in drop]


def _upstream_base() -> str:
    return settings.LLM_SERVER_URL.rstrip("/")


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(path: str, request: Request) -> StreamingResponse:
    base = _upstream_base()
    target_url = f"{base}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Read the inbound body once. FastAPI's Request.body() reads to memory
    # which is fine for UI/API traffic — llama-swap doesn't accept huge
    # uploads on the surfaces we're proxying.
    body = await request.body()
    fwd_headers = _filter_request_headers(request.headers)

    client: httpx.AsyncClient = request.app.state.http_client
    req = client.build_request(
        method=request.method,
        url=target_url,
        headers=fwd_headers,
        content=body if body else None,
    )
    try:
        upstream = await client.send(req, stream=True)
    except httpx.RequestError as exc:
        _logger.warning("engine proxy upstream error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Engine proxy upstream unreachable: {exc.__class__.__name__}",
        )

    out_headers = dict(_filter_response_headers(upstream.headers))
    if "location" in out_headers:
        out_headers["location"] = _rewrite_location(out_headers["location"])

    content_type = upstream.headers.get("content-type")
    rewrite = _should_rewrite_body(content_type)

    if rewrite:
        # Buffer the response so we can rewrite absolute paths in-place.
        # llama-swap's HTML/JS payloads are small (kilobytes), so this is
        # acceptable; streaming endpoints (text/event-stream) skip this
        # branch and pass through chunk-by-chunk below.
        try:
            raw = await upstream.aread()
        finally:
            await upstream.aclose()
        rewritten = _rewrite_body(raw)
        return Response(
            content=rewritten,
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=content_type,
        )

    async def iter_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        iter_body(),
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=content_type,
    )
