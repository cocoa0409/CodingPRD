"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_operator_headers():
    return TEST_USERS["platform_operator_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def data_engineer_headers():
    return TEST_USERS["data_engineer_headers"]


@pytest.fixture
def share_admin_headers():
    return TEST_USERS["share_admin_headers"]