"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, api_client, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def network_manager_headers():
    return TEST_USERS["network_manager_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def parts_manager_headers():
    return TEST_USERS["parts_manager_headers"]


@pytest.fixture
def rebuild_specialist_headers():
    return TEST_USERS["rebuild_specialist_headers"]


@pytest.fixture
def technician_supervisor_headers():
    return TEST_USERS["technician_supervisor_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def finance_partner_headers():
    return TEST_USERS["finance_partner_headers"]


@pytest.fixture
def input_dealer_headers():
    return TEST_USERS["input_dealer_headers"]