"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_wholesaler_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def wholesaler_headers():
    return TEST_USERS["wholesaler_headers"]


@pytest.fixture
def ws_headers():
    """Factory fixture: ws_headers(wholesaler_id) -> ownership-correct headers."""
    return make_wholesaler_headers
