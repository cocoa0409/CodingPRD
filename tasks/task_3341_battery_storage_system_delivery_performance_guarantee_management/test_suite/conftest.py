"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def project_developer_headers():
    return TEST_USERS["project_developer_headers"]


@pytest.fixture
def performance_engineer_headers():
    return TEST_USERS["performance_engineer_headers"]


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]


@pytest.fixture
def service_engineer_headers():
    return TEST_USERS["service_engineer_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def safety_authority_headers():
    return TEST_USERS["safety_authority_headers"]


@pytest.fixture
def market_operator_headers():
    return TEST_USERS["market_operator_headers"]
