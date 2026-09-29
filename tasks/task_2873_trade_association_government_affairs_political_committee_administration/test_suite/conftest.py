"""Shared pytest fixtures for the Government Affairs API suite.

Every test runs against a freshly restarted server with an empty database, so
there is nothing to tear down: each test builds the state it needs from the
documented endpoints.
"""
import pytest

from test_helpers import api_client
from test_helpers.test_users import (
    NO_HEADERS,
    TEST_USERS,
    make_member_delegate_headers,
)


@pytest.fixture(scope="session")
def api():
    """The endpoint client for the API under test."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def compliance_headers_2():
    return TEST_USERS["compliance_headers_2"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trustee_headers"]


@pytest.fixture
def trustee_headers_2():
    return TEST_USERS["trustee_headers_2"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]


@pytest.fixture
def no_headers():
    return NO_HEADERS


@pytest.fixture
def member_headers():
    """Builder for a member company acting for itself."""
    return make_member_delegate_headers
