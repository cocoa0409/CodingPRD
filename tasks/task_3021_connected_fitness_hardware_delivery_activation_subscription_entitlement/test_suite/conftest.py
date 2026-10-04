"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle: it restarts the API server via start.sh before
every individual test, so every test starts against an empty database and builds
its own entities. This file only wires up fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def membership_owner_headers():
    """Fallback owner headers for calls that are not ownership-gated."""
    return TEST_USERS["membership_owner_headers"]


@pytest.fixture
def service_technician_headers():
    return TEST_USERS["service_technician_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]