"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def appointing_executive_headers():
    return TEST_USERS["appointing_executive_headers"]


@pytest.fixture
def field_manager_headers():
    return TEST_USERS["field_manager_headers"]


@pytest.fixture
def agency_principal_headers():
    return TEST_USERS["agency_principal_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def regulatory_board_headers():
    return TEST_USERS["regulatory_board_headers"]


@pytest.fixture
def staff_member_headers():
    return TEST_USERS["staff_member_headers"]