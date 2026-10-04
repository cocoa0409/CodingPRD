"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner manages the server lifecycle."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def panel_headers():
    return TEST_USERS["panel_headers"]


@pytest.fixture
def appeals_headers():
    return TEST_USERS["appeals_headers"]


@pytest.fixture
def petitioner_headers():
    # Shared constant — non-ownership calls only.
    return TEST_USERS["petitioner_headers"]


@pytest.fixture
def patent_owner_headers():
    # Shared constant — non-ownership calls only.
    return TEST_USERS["patent_owner_headers"]
