"""Pytest fixtures exposing the stewardship test_helpers infrastructure."""
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
def product_manager_headers():
    return TEST_USERS["product_manager_headers"]


@pytest.fixture
def regulatory_manager_headers():
    return TEST_USERS["regulatory_manager_headers"]


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def quality_auditor_headers():
    return TEST_USERS["quality_auditor_headers"]


@pytest.fixture
def technical_engineer_headers():
    return TEST_USERS["technical_engineer_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def converter_headers():
    return TEST_USERS["converter_headers"]


@pytest.fixture
def distributor_headers():
    return TEST_USERS["distributor_headers"]
