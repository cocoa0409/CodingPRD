"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def region_manager_headers():
    return TEST_USERS["region_manager_headers"]


@pytest.fixture
def channel_director_headers():
    return TEST_USERS["channel_director_headers"]


@pytest.fixture
def color_lab_admin_headers():
    return TEST_USERS["color_lab_admin_headers"]


@pytest.fixture
def equipment_tech_headers():
    return TEST_USERS["equipment_tech_headers"]
