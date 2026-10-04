"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def franchisor_ops_headers():
    return TEST_USERS["franchisor_ops_headers"]


@pytest.fixture
def mediator_headers():
    return TEST_USERS["mediator_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def development_agent_headers():
    return TEST_USERS["development_agent_headers"]


@pytest.fixture
def franchisee_headers():
    return TEST_USERS["franchisee_headers"]
