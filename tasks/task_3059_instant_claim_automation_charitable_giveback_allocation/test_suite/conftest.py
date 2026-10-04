"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]


@pytest.fixture
def underwriting_admin_headers():
    return TEST_USERS["underwriting_admin_headers"]


@pytest.fixture
def adjuster_1_headers():
    return TEST_USERS["adjuster_1_headers"]


@pytest.fixture
def adjuster_2_headers():
    return TEST_USERS["adjuster_2_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
