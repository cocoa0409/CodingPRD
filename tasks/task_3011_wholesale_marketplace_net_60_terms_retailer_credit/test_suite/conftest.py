"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle, API_BASE_URL and PYTHONPATH; tests never
start, stop or health-check the server. The server is relaunched before every
individual test, so each test begins against an empty database and builds the
state it needs through the PRD's own endpoints.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANON,
    RISK,
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def risk_headers():
    return TEST_USERS["risk_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
