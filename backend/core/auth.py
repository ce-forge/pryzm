"""Bearer-token authentication dependency.

Single shared token configured via PRYZM_API_TOKEN env var. Not a user system.
"""
import hmac
from typing import Annotated, Optional

from fastapi import Header, HTTPException, status

from config import settings


_BEARER_PREFIX = "Bearer "


def require_token(
    authorization: Annotated[Optional[str], Header()] = None,
) -> None:
    """FastAPI dependency. Raises 401 if the bearer token is missing or wrong.

    Constant-time compares with hmac.compare_digest to avoid timing attacks.
    """
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
        )

    presented = authorization[len(_BEARER_PREFIX):]
    if not hmac.compare_digest(presented, settings.PRYZM_API_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
