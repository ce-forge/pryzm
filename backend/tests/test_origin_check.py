"""Origin allowlist middleware: state-changing requests with a foreign Origin
must be rejected with 403; absent Origin and allowed Origin must pass.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.origin_check import OriginCheckMiddleware


def _app(allowed: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware, allowed_origins=allowed)

    @app.get("/anything")
    def get_anything():
        return {"ok": True}

    @app.post("/anything")
    def post_anything():
        return {"ok": True}

    return app


def test_post_with_foreign_origin_returns_403():
    client = TestClient(_app(["http://localhost:3000"]))
    resp = client.post("/anything", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert "origin" in resp.json()["detail"].lower()


def test_post_with_allowed_origin_passes():
    client = TestClient(_app(["http://localhost:3000"]))
    resp = client.post("/anything", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200


def test_post_with_no_origin_passes():
    """curl / native apps don't carry the CSRF threat model — allow them."""
    client = TestClient(_app(["http://localhost:3000"]))
    resp = client.post("/anything")
    assert resp.status_code == 200


def test_get_with_foreign_origin_passes():
    """GET is not state-changing — the middleware doesn't gate it."""
    client = TestClient(_app(["http://localhost:3000"]))
    resp = client.get("/anything", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200


def test_delete_with_foreign_origin_returns_403():
    """All four state-changing methods are gated."""
    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware, allowed_origins=["http://localhost:3000"])

    @app.delete("/anything")
    def del_anything():
        return {"ok": True}

    client = TestClient(app)
    resp = client.delete("/anything", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
