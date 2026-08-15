"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def photo_editor_headers():
    return TEST_USERS["photo_editor_headers"]


@pytest.fixture
def rights_manager_headers():
    return TEST_USERS["rights_manager_headers"]


@pytest.fixture
def rights_manager_alice_headers():
    return TEST_USERS["rights_manager_alice_headers"]


@pytest.fixture
def rights_manager_bob_headers():
    return TEST_USERS["rights_manager_bob_headers"]


@pytest.fixture
def archivist_headers():
    return TEST_USERS["archivist_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
