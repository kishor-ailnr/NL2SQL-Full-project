"""
Shared pytest fixtures for the NL2SQL test suite.

Fixtures defined here are automatically available to all test_*.py files
in this package (conftest.py is automatically discovered by pytest).

Key fixtures:
  client          — Starlette TestClient wrapping the FastAPI app (function scope)
  hospital_sid    — session_id for a freshly connected hospital demo (function scope)
  ecommerce_sid   — session_id for a freshly connected ecommerce demo (function scope)
"""

import pytest

from app.main import app
from app.routers.query import reset_rate_limits
from app.services.sql_generator import clear_query_cache


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client():
    """Return a TestClient for the FastAPI app.

    Uses function scope so each test gets a clean request state.
    The TestClient calls lifespan startup/shutdown (init_db, preload_demo_cache).
    """
    from starlette.testclient import TestClient
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Before every test: clear in-memory caches and rate limiters.

    Using autouse=True means every test automatically gets a clean slate
    without having to import or call these manually.
    """
    reset_rate_limits()
    clear_query_cache()
    yield
    # Teardown (after test) — nothing needed for in-memory state.


@pytest.fixture(scope="function")
def hospital_sid(client):
    """Connect to the hospital demo DB and return a fresh session_id."""
    resp = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "hospital"})
    assert resp.status_code == 200, f"Failed to connect to hospital demo: {resp.text}"
    data = resp.json()
    assert "patients" in data["tables"], "Hospital demo must expose a patients table"
    return data["session_id"]


@pytest.fixture(scope="function")
def ecommerce_sid(client):
    """Connect to the ecommerce demo DB and return a fresh session_id."""
    resp = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "ecommerce"})
    assert resp.status_code == 200, f"Failed to connect to ecommerce demo: {resp.text}"
    data = resp.json()
    assert "orders" in data["tables"] or "products" in data["tables"], \
        "Ecommerce demo must expose orders or products table"
    return data["session_id"]


# ---------------------------------------------------------------------------
# Helpers (not fixtures — imported directly by tests that need them)
# ---------------------------------------------------------------------------

def post_query(client, session_id: str, text: str, conversation_id: str = None):
    """POST /api/query and return (status_code, response_json)."""
    payload = {"session_id": session_id, "text": text, "language": "auto"}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    resp = client.post("/api/query", json=payload)
    return resp.status_code, resp.json()
