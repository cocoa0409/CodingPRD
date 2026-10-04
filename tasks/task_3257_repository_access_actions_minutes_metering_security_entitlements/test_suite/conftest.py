"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def enterprise_admin_headers():
    return TEST_USERS["enterprise_admin_headers"]


@pytest.fixture
def org_admin_headers():
    return TEST_USERS["org_admin_headers"]


@pytest.fixture
def runner_agent_headers():
    return TEST_USERS["runner_agent_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
