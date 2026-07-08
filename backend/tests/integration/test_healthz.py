"""Integration test hitting the running stack via Nginx TLS.

Prerequisites:
- `make up` stack is running.
- Self-signed cert in place.

Intended to be run from host against a live docker-compose stack, not in CI
without additional setup.
"""

import os

import httpx
import pytest

PUBLIC_URL = os.environ.get("TLS_URL", "")

# These tests hit Nginx TLS specifically. They are opt-in via TLS_URL —
# run from the host with `TLS_URL=https://localhost pytest ...`. Inside
# the api container nginx is not reachable at https://localhost, so we skip.
_needs_tls = pytest.mark.skipif(
    not PUBLIC_URL.startswith("https://"),
    reason="set TLS_URL=https://localhost to run TLS tests from host",
)


@_needs_tls
@pytest.mark.integration
def test_healthz_returns_ok() -> None:
    resp = httpx.get(f"{PUBLIC_URL}/healthz", verify=False, timeout=5.0)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "Fylix"


@_needs_tls
@pytest.mark.integration
def test_http_redirects_to_https() -> None:
    resp = httpx.get(
        PUBLIC_URL.replace("https://", "http://"),
        follow_redirects=False,
        timeout=5.0,
    )
    assert resp.status_code == 301
    assert resp.headers["location"].startswith("https://")


@_needs_tls
@pytest.mark.integration
def test_security_headers_present() -> None:
    resp = httpx.get(f"{PUBLIC_URL}/healthz", verify=False, timeout=5.0)
    assert "strict-transport-security" in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
