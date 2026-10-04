"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def licensee_headers():
    return TEST_USERS["licensee_headers"]


@pytest.fixture
def royalty_ops_headers():
    return TEST_USERS["royalty_ops_headers"]


@pytest.fixture
def payee_admin_headers():
    return TEST_USERS["payee_admin_headers"]


@pytest.fixture
def statutory_board_headers():
    return TEST_USERS["statutory_board_headers"]


@pytest.fixture
def royalty_auditor_headers():
    return TEST_USERS["royalty_auditor_headers"]


@pytest.fixture
def matching_agent_headers():
    return TEST_USERS["matching_agent_headers"]
