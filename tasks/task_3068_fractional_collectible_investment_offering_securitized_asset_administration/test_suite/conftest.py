"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and API_BASE_URL injection, and restarts the
server (empty database) before every individual test, so no test may rely on
state another test created.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def issuer_headers():
    return TEST_USERS["issuer_ops_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def transfer_agent_headers():
    return TEST_USERS["transfer_agent_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]