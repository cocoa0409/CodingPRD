"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle, PYTHONPATH and API_BASE_URL are managed by the runner.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def release_manager_headers():
    return TEST_USERS["release_manager_headers"]


@pytest.fixture
def environment_admin_headers():
    return TEST_USERS["environment_admin_headers"]


@pytest.fixture
def storage_archivist_headers():
    return TEST_USERS["storage_archivist_headers"]


@pytest.fixture
def security_auditor_headers():
    return TEST_USERS["security_auditor_headers"]


@pytest.fixture
def app_developer_headers():
    return TEST_USERS["app_developer_headers"]