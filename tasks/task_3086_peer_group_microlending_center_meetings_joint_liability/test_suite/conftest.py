"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_center_manager_headers,
    make_member_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]


@pytest.fixture
def branch_manager_b_headers():
    return TEST_USERS["branch_manager_b_headers"]


@pytest.fixture
def field_officer_headers():
    return TEST_USERS["field_officer_headers"]


@pytest.fixture
def center_manager_headers():
    return TEST_USERS["center_manager_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def make_cm_headers():
    return make_center_manager_headers


@pytest.fixture
def make_borrower_headers():
    return make_member_headers
