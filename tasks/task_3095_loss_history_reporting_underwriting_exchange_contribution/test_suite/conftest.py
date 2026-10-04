"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_admin_headers,
    make_compliance_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return make_admin_headers()


@pytest.fixture
def compliance_headers():
    return make_compliance_headers()
