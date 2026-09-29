"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def vineyard_manager_headers():
    return TEST_USERS["vineyard_manager_headers"]


@pytest.fixture
def vineyard_manager_alt_headers():
    return TEST_USERS["vineyard_manager_alt_headers"]


@pytest.fixture
def agronomist_headers():
    return TEST_USERS["agronomist_headers"]


@pytest.fixture
def agronomist_alt_headers():
    return TEST_USERS["agronomist_alt_headers"]


@pytest.fixture
def applicator_headers():
    return TEST_USERS["applicator_headers"]


@pytest.fixture
def applicator_alt_headers():
    return TEST_USERS["applicator_alt_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def controller_alt_headers():
    return TEST_USERS["controller_alt_headers"]
