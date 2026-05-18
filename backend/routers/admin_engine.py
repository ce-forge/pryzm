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
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from core import cookie_auth


router = APIRouter(
    prefix="/api/admin/engine",
    tags=["admin", "engine"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


_logger = logging.getLogger(__name__)


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

    async def iter_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        iter_body(),
        status_code=upstream.status_code,
        headers=dict(_filter_response_headers(upstream.headers)),
        media_type=upstream.headers.get("content-type"),
    )
