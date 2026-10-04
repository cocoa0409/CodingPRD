"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def regional_manager_headers():
    return TEST_USERS["regional_manager_headers"]


@pytest.fixture
def stand_operator_headers():
    return TEST_USERS["stand_operator_headers"]


@pytest.fixture
def shift_lead_headers():
    return TEST_USERS["shift_lead_headers"]


@pytest.fixture
def crew_member_headers():
    return TEST_USERS["crew_member_headers"]


@pytest.fixture
def loyalty_customer_headers():
    return TEST_USERS["loyalty_customer_headers"]
