"""Pytest fixtures exposing the test_helpers infrastructure.

The runner (prd-bench-local-runner) owns the server lifecycle and PYTHONPATH;
these fixtures only bridge the helper package into the test modules. Every
test runs against a freshly booted server with an empty database, so each
test builds all of its own state through the API.
"""

import pytest
from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """ManufacturerAdmin headers (opaque identity; canonical shared entry)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def dealer_headers():
    """Unbound DealerRep headers — only for tests that do not exercise
    ownership (role-denied or bad-payload calls before any resource exists)."""
    return TEST_USERS["dealer_headers"]


@pytest.fixture
def end_user_headers():
    """Unbound EndUserRep headers — same restriction as dealer_headers."""
    return TEST_USERS["end_user_headers"]
