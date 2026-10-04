"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; the session-
scoped client below is the shared ApiClient singleton from test_helpers.
Each test starts against a fresh database (the server is restarted before
every test), so every test builds its own preconditions through the
declared endpoints.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin"]


@pytest.fixture
def state_dot_planner_headers() -> dict:
    return TEST_USERS["state_dot_planner"]


@pytest.fixture
def state_dot_engineer_headers() -> dict:
    return TEST_USERS["state_dot_engineer"]


@pytest.fixture
def state_dot_engineer_alt_headers() -> dict:
    return TEST_USERS["state_dot_engineer_alt"]


@pytest.fixture
def fhwa_division_admin_headers() -> dict:
    return TEST_USERS["fhwa_division_admin"]


@pytest.fixture
def fhwa_reviewer_headers() -> dict:
    return TEST_USERS["fhwa_reviewer"]


@pytest.fixture
def fhwa_reviewer_alt_headers() -> dict:
    return TEST_USERS["fhwa_reviewer_alt"]
