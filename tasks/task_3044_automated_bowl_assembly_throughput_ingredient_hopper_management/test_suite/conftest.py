"""Pytest fixtures exposing test_helpers infrastructure.

The harness restarts the API server before every individual test, so each test
starts against an empty database and builds its preconditions through the
public API. The server base URL is injected via the API_BASE_URL environment
variable by the runner.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return ApiClient()


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def shift_manager_headers():
    return TEST_USERS["shift_manager_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def prep_cook_headers():
    return TEST_USERS["prep_cook_headers"]


@pytest.fixture
def quality_lead_headers():
    return TEST_USERS["quality_lead_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
