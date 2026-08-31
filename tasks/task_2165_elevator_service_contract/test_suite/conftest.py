"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ANONYMOUS_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """ProgramAdministrator pa-1."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def second_admin_headers():
    """A second ProgramAdministrator pa-2, for segregation-of-duties tests."""
    return TEST_USERS["second_admin_headers"]


@pytest.fixture
def inspector_headers():
    """StateInspector si-1 (never a contract party)."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def dispatcher_headers():
    """FireDispatcher fd-1 (never a contract party)."""
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def building_manager_headers():
    """BuildingManager bm-1 — matches the default contract payload."""
    return TEST_USERS["building_manager_headers"]


@pytest.fixture
def contractor_headers():
    """ServiceContractor sc-1 — matches the default contract payload."""
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def anonymous_headers():
    """No X-User-ID and no X-User-Role at all."""
    return ANONYMOUS_HEADERS
