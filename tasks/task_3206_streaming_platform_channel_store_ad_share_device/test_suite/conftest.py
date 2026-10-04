"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def adops_headers():
    return TEST_USERS["adops_headers"]


@pytest.fixture
def publisher_headers():
    return TEST_USERS["publisher_headers"]


@pytest.fixture
def viewer_headers():
    return TEST_USERS["viewer_headers"]


@pytest.fixture
def manufacturer_headers():
    return TEST_USERS["manufacturer_headers"]
