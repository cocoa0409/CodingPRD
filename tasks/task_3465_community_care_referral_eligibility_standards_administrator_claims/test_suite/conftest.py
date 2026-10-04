"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is managed externally; tests assume the API is already
reachable and that every test starts against a freshly restarted server
(empty database, logical clock at 2026-09-01T00:00:00Z).
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle owned by the runner)."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def eligibility_clerk_headers() -> dict:
    return TEST_USERS["eligibility_clerk_headers"]


@pytest.fixture
def care_coordinator_headers() -> dict:
    return TEST_USERS["care_coordinator_headers"]


@pytest.fixture
def network_manager_headers() -> dict:
    return TEST_USERS["network_manager_headers"]


@pytest.fixture
def system_pharmacist_headers() -> dict:
    return TEST_USERS["system_pharmacist_headers"]
