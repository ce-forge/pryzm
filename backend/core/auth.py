"""Bearer-token authentication dependency.

Single shared token configured via PRYZM_API_TOKEN env var. Not a user system.
"""
import hmac
from typing import Annotated, Optional

from fastapi import Header, HTTPException, Query, status

from config import settings


_BEARER_PREFIX = "Bearer "


def require_token(
    authorization: Annotated[Optional[str], Header()] = None,
    token: Annotated[Optional[str], Query()] = None,
) -> None:
    """FastAPI dependency. Raises 401 if the bearer token is missing or wrong.

    Accepts the token either in `Authorization: Bearer <token>` (the
    normal path used by `apiFetch`) or as a `?token=<token>` query
    parameter (the SSE-friendly fallback — EventSource can't set
    custom headers, so SSE clients pass the token in the URL). The
    query path is the documented short-term concession; the long-term
    end-state is cookie-auth, which is on the broader roadmap.

    Constant-time compares with hmac.compare_digest to avoid timing attacks.
    """
    presented: Optional[str] = None
    if authorization is not None and authorization.startswith(_BEARER_PREFIX):
        presented = authorization[len(_BEARER_PREFIX):]
    elif token:
        presented = token

    if presented is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed credentials.",
        )

    if not hmac.compare_digest(presented, settings.PRYZM_API_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
