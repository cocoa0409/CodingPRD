"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def practice_admin_headers():
    """Fallback only. Ownership-gated calls must use make_practice_admin_headers
    with the real Practice.id."""
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def revenue_cycle_manager_headers():
    return TEST_USERS["revenue_cycle_manager_headers"]


@pytest.fixture
def payer_adjudicator_headers():
    return TEST_USERS["payer_adjudicator_headers"]


@pytest.fixture
def network_analyst_headers():
    return TEST_USERS["network_analyst_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]