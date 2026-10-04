"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is handled by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def model_coordinator_headers():
    return TEST_USERS["model_coordinator_headers"]


@pytest.fixture
def shop_foreman_headers():
    return TEST_USERS["shop_foreman_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def procurement_headers():
    return TEST_USERS["procurement_headers"]


@pytest.fixture
def general_foreman_headers():
    return TEST_USERS["general_foreman_headers"]


@pytest.fixture
def install_foreman_headers():
    return TEST_USERS["install_foreman_headers"]