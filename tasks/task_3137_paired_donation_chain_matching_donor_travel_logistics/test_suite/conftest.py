"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def registry_admin_headers():
    return TEST_USERS["registry_admin_headers"]


@pytest.fixture
def match_operator_headers():
    return TEST_USERS["match_operator_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def center_coordinator_headers():
    return TEST_USERS["center_coordinator_headers"]
