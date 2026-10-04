"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def moderator_headers():
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def moderator2_headers():
    return TEST_USERS["moderator2_headers"]


@pytest.fixture
def policy_analyst_headers():
    return TEST_USERS["policy_analyst_headers"]


@pytest.fixture
def policy_analyst2_headers():
    return TEST_USERS["policy_analyst2_headers"]


@pytest.fixture
def policy_analyst3_headers():
    return TEST_USERS["policy_analyst3_headers"]


@pytest.fixture
def imagery_operator_headers():
    return TEST_USERS["imagery_operator_headers"]


@pytest.fixture
def routing_engineer_headers():
    return TEST_USERS["routing_engineer_headers"]
