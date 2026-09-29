"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def numbering_admin_headers():
    return TEST_USERS["numbering_admin_headers"]


@pytest.fixture
def porting_specialist_headers():
    return TEST_USERS["porting_specialist_headers"]


@pytest.fixture
def carrier_liaison_headers():
    return TEST_USERS["carrier_liaison_headers"]


@pytest.fixture
def e911_validator_headers():
    return TEST_USERS["e911_validator_headers"]


@pytest.fixture
def security_analyst_headers():
    return TEST_USERS["security_analyst_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]
