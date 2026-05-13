"""Shared FastAPI dependencies for async resources.

The HTTP client is created once in main.py's lifespan and stored on
app.state.http_client. Routes that need it should depend on get_http_client.
"""
from fastapi import Request

import httpx


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient created in lifespan."""
    return request.app.state.http_client
