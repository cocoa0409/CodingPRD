"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def energy_manager_headers():
    return TEST_USERS["energy_manager_headers"]


@pytest.fixture
def trading_analyst_headers():
    return TEST_USERS["trading_analyst_headers"]


@pytest.fixture
def smelter_manager_headers():
    return TEST_USERS["smelter_manager_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def vp_operations_headers():
    return TEST_USERS["vp_operations_headers"]


@pytest.fixture
def ehs_manager_headers():
    return TEST_USERS["ehs_manager_headers"]
