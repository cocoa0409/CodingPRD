"""Pytest fixtures exposing the member-station network test helpers."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def station_manager_headers():
    return TEST_USERS["station_manager_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def program_editor_headers():
    return TEST_USERS["program_editor_headers"]


@pytest.fixture
def underwriting_headers():
    return TEST_USERS["underwriting_headers"]


@pytest.fixture
def governance_headers():
    return TEST_USERS["governance_headers"]