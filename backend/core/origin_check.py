"""Origin allowlist middleware — CSRF defence in depth.

The session cookie is SameSite=Lax, which blocks cross-site form POSTs in
modern browsers. This middleware adds a second layer: any state-changing
request whose `Origin` header is set and is NOT in the allowlist is
rejected with 403.

Absent Origin is allowed: curl, native apps, and same-origin GETs don't
carry the CSRF threat model. Browsers always populate Origin on
POST/PUT/PATCH/DELETE.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class OriginCheckMiddleware(BaseHTTPMiddleware):
    STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app, allowed_origins: list[str]):
        super().__init__(app)
        self._allowed = frozenset(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method in self.STATE_CHANGING:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self._allowed:
                return JSONResponse(
                    {"detail": "Origin not allowed."},
                    status_code=403,
                )
        return await call_next(request)
