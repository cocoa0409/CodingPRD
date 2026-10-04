"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the API is
already reachable at API_BASE_URL and starts every test against an empty
database whose logical clock reads 2026-09-01T00:00:00Z (PRD section 2.4).
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def specialist_headers() -> dict:
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def decider_headers() -> dict:
    return TEST_USERS["managing_attorney_headers"]


@pytest.fixture
def attorney_headers() -> dict:
    return TEST_USERS["staff_attorney_headers"]


@pytest.fixture
def analyst_headers() -> dict:
    return TEST_USERS["evidence_analyst_headers"]


@pytest.fixture
def advocate_headers() -> dict:
    return TEST_USERS["client_services_advocate_headers"]


@pytest.fixture
def policy_headers() -> dict:
    return TEST_USERS["policy_director_headers"]


@pytest.fixture
def client_headers() -> dict:
    """Fallback Client-role headers that match no real Client id (non-ownership probes only)."""
    return TEST_USERS["client_headers"]
