"""
tests/test_security.py
-----------------------
Security-layer tests: response headers, upload validation, and rate limiting.
Derived from: test_security_audit.py, security_hardening pass (scratch tests).
These tests are network-free (use TestClient) and zero-cost (no Gemini calls).
"""

import io
import time

import pytest

from app.routers.query import (
    _QUERY_TIMESTAMPS,
    _GLOBAL_KEY,
    GLOBAL_RATE_LIMIT_PER_MINUTE,
    RATE_LIMIT_PER_MINUTE,
    reset_rate_limits,
    check_rate_limit,
)
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# 1. Security Headers — every response must carry them
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Verify SecurityHeadersMiddleware injects all required headers."""

    def _headers(self, client):
        return client.get("/health").headers

    def test_x_content_type_options(self, client):
        assert self._headers(client).get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        assert self._headers(client).get("X-Frame-Options") == "DENY"

    def test_csp_present(self, client):
        assert "Content-Security-Policy" in self._headers(client)

    def test_csp_frame_ancestors_none(self, client):
        csp = self._headers(client).get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp

    def test_csp_default_src_self(self, client):
        csp = self._headers(client).get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp

    def test_csp_media_src(self, client):
        csp = self._headers(client).get("Content-Security-Policy", "")
        assert "media-src 'self' data: blob:" in csp

    def test_referrer_policy_present(self, client):
        assert "Referrer-Policy" in self._headers(client)

    def test_headers_present_on_api_endpoints(self, client):
        """Headers must appear on API responses too, not just /health."""
        resp = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "hospital"})
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# 2. File Upload Validation
# ---------------------------------------------------------------------------

class TestFileUploadValidation:
    def test_valid_small_csv_returns_200(self, client):
        csv = b"id,name,age\n1,Alice,30\n2,Bob,25\n"
        resp = client.post(
            "/api/upload-db",
            files={"file": ("data.csv", io.BytesIO(csv), "text/csv")},
        )
        assert resp.status_code == 200

    def test_wrong_extension_txt_returns_400(self, client):
        resp = client.post(
            "/api/upload-db",
            files={"file": ("data.txt", io.BytesIO(b"col,val\nfoo,bar\n"), "text/plain")},
        )
        assert resp.status_code == 400
        assert "unsupported" in resp.json()["detail"].lower()

    def test_wrong_extension_exe_returns_400(self, client):
        resp = client.post(
            "/api/upload-db",
            files={"file": ("payload.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_oversized_file_returns_413(self, client):
        # 6 MB > 5 MB limit
        big = b"id,name\n" + b"1,Alice\n" * (6 * 1024 * 1024 // 8)
        resp = client.post(
            "/api/upload-db",
            files={"file": ("big.csv", io.BytesIO(big), "text/csv")},
        )
        assert resp.status_code == 413
        assert "5 mb" in resp.json()["detail"].lower()

    def test_empty_csv_returns_400(self, client):
        resp = client.post(
            "/api/upload-db",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_valid_sql_extension_accepted(self, client):
        sql_bytes = b"CREATE TABLE t (id INTEGER);\nINSERT INTO t VALUES (1);\n"
        resp = client.post(
            "/api/upload-db",
            files={"file": ("schema.sql", io.BytesIO(sql_bytes), "application/sql")},
        )
        # Either 200 or a domain error (e.g. table conflict) but NOT 400/413
        assert resp.status_code not in (400, 413)


# ---------------------------------------------------------------------------
# 3. Rate Limiting — unit tests against check_rate_limit() directly
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Pure unit tests: no HTTP calls, no Gemini, just the sliding-window logic."""

    def test_global_limit_raises_429_when_bucket_full(self):
        reset_rate_limits()
        now = time.time()
        _QUERY_TIMESTAMPS[_GLOBAL_KEY] = [now - 1] * GLOBAL_RATE_LIMIT_PER_MINUTE
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("some-session-id")
        assert exc_info.value.status_code == 429

    def test_global_limit_error_detail_mentions_load(self):
        reset_rate_limits()
        now = time.time()
        _QUERY_TIMESTAMPS[_GLOBAL_KEY] = [now - 1] * GLOBAL_RATE_LIMIT_PER_MINUTE
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("any-session")
        detail = exc_info.value.detail.lower()
        assert "load" in detail or "limit" in detail or "wait" in detail

    def test_per_session_limit_raises_429_when_bucket_full(self):
        reset_rate_limits()
        now = time.time()
        _QUERY_TIMESTAMPS["test-session"] = [now - 1] * RATE_LIMIT_PER_MINUTE
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("test-session")
        assert exc_info.value.status_code == 429

    def test_per_session_limit_error_has_retry_after_header(self):
        reset_rate_limits()
        now = time.time()
        _QUERY_TIMESTAMPS["test-session"] = [now - 1] * RATE_LIMIT_PER_MINUTE
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("test-session")
        assert "Retry-After" in exc_info.value.headers

    def test_fresh_session_passes_through_without_exception(self):
        reset_rate_limits()
        # Must not raise
        check_rate_limit("fresh-session-abc")

    def test_global_bucket_incremented_after_successful_request(self):
        reset_rate_limits()
        before = len(_QUERY_TIMESTAMPS.get(_GLOBAL_KEY, []))
        check_rate_limit("new-session-xyz")
        after = len(_QUERY_TIMESTAMPS.get(_GLOBAL_KEY, []))
        assert after == before + 1

    def test_session_bucket_incremented_after_successful_request(self):
        reset_rate_limits()
        sid = "my-session-123"
        check_rate_limit(sid)
        assert len(_QUERY_TIMESTAMPS[sid]) == 1

    def test_sliding_window_expires_old_timestamps(self):
        """Timestamps older than 60s must not count toward the limit."""
        reset_rate_limits()
        sid = "expire-test-session"
        now = time.time()
        # Fill with timestamps 65 seconds ago (outside the 60s window)
        _QUERY_TIMESTAMPS[sid] = [now - 65] * RATE_LIMIT_PER_MINUTE
        # This should NOT raise — the old timestamps are outside the window
        check_rate_limit(sid)

    def test_expired_sessions_are_purged_from_timestamps_dict(self):
        """UE-03: Sessions with timestamps older than the 60s window must be purged from dictionary keys."""
        reset_rate_limits()
        now = time.time()
        # Create an abandoned session with timestamps 65 seconds ago
        _QUERY_TIMESTAMPS["abandoned-session-old"] = [now - 65]
        # Active request from a different session
        check_rate_limit("active-session-new")
        # 'abandoned-session-old' must have been purged from the dictionary keys
        assert "abandoned-session-old" not in _QUERY_TIMESTAMPS
        assert "active-session-new" in _QUERY_TIMESTAMPS
