"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def operations_coordinator_headers():
    return TEST_USERS["operations_coordinator_headers"]


@pytest.fixture
def transaction_coordinator_headers():
    return TEST_USERS["transaction_coordinator_headers"]


@pytest.fixture
def listing_agent_headers():
    return TEST_USERS["listing_agent_headers"]


@pytest.fixture
def associate_agent_headers():
    return TEST_USERS["associate_agent_headers"]