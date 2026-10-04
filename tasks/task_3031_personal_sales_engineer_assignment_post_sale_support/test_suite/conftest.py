"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, api_client

from test_helpers.fixtures import (
    ANONYMOUS,
    PLATFORM_ADMIN,
    SALES_OPS,
    SERVICE_DEPT,
    SETUP_TECH,
    SUPPORT_AGENT,
)
from test_helpers.test_users import TEST_USERS, make_engineer_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return PLATFORM_ADMIN


@pytest.fixture
def sales_ops_headers():
    return SALES_OPS


@pytest.fixture
def setup_technician_headers():
    return SETUP_TECH


@pytest.fixture
def support_agent_headers():
    return SUPPORT_AGENT


@pytest.fixture
def service_department_headers():
    return SERVICE_DEPT


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def engineer_headers_for():
    """Return make_engineer_headers so tests can build ownership-gated headers."""
    return make_engineer_headers