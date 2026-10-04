"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; tests assume the server
is already reachable at API_BASE_URL.
"""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_business_rep_headers,
    make_consumer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the
    runner, which restarts the server before every test."""
    return api_client


# --- Role header fixtures -------------------------------------------------
# Opaque roles: the shared constant is the canonical form.
@pytest.fixture
def bureau_admin_headers() -> dict:
    return TEST_USERS["bureau_admin_headers"]


@pytest.fixture
def standards_reviewer_headers() -> dict:
    return TEST_USERS["standards_reviewer_headers"]


# Entity-backed roles: these shared constants are ONLY for assertions whose
# outcome does not depend on the caller owning the resource (e.g. 400-schema
# or 404 probes). Ownership-gated calls must use the builders below with the
# actual entity id (PRD §2.1: X-User-ID equals the Business.id / Consumer.id).
@pytest.fixture
def business_rep_headers() -> dict:
    return TEST_USERS["business_rep_headers"]


@pytest.fixture
def consumer_headers() -> dict:
    return TEST_USERS["consumer_headers"]


# Per-instance builders for the entity-backed roles.
@pytest.fixture
def make_business_rep_headers_for():
    """Build BusinessRep headers bound to a concrete Business.id."""
    return make_business_rep_headers


@pytest.fixture
def make_consumer_headers_for():
    """Build Consumer headers bound to a concrete Consumer.id."""
    return make_consumer_headers
