"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def rights_holder_headers():
    return TEST_USERS["rights_holder_headers"]


@pytest.fixture
def playlist_editor_headers():
    return TEST_USERS["playlist_editor_headers"]


@pytest.fixture
def editorial_lead_headers():
    return TEST_USERS["editorial_lead_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]
