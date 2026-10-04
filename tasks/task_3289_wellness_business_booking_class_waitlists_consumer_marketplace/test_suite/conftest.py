"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is owned by the runner; these fixtures only hand tests a
shared client plus the per-role header builders.
"""
import pytest

from test_helpers import TEST_USERS, api_client, ApiClient, make_client_headers, \
    make_operator_headers, make_platform_admin_headers, make_staff_member_headers, \
    make_studio_owner_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def make_owner():
    """Returns the builder for a studio owner acting as a specific studio."""
    return make_studio_owner_headers


@pytest.fixture
def make_client():
    """Returns the builder for a client acting as a specific client."""
    return make_client_headers


@pytest.fixture
def make_staff():
    """Returns the builder for a staff member acting as a specific staff row."""
    return make_staff_member_headers


@pytest.fixture
def make_admin():
    return make_platform_admin_headers


@pytest.fixture
def make_operator():
    return make_operator_headers