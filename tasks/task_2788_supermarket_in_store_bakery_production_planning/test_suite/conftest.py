"""Shared pytest fixtures for the in-store bakery production API suite.

The harness restarts the server before every test, so each test starts from an
empty database and builds every precondition it needs through the API itself.
PRD §2.11 gives the server a logical clock whose startup value is exactly
``2026-08-01T00:00:00Z``; every composite helper in ``test_helpers`` pins that
clock explicitly before it does anything else.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    make_department_manager_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client, one method per endpoint the PRD defines."""
    return api_client


@pytest.fixture
def regional_admin_headers():
    """PRD §2.1: a chain-level operator who provisions reference data."""
    return TEST_USERS["regional_admin_headers"]


@pytest.fixture
def baker_headers():
    """PRD §2.1: the production-floor operator (opaque identity)."""
    return TEST_USERS["baker_headers"]


@pytest.fixture
def second_baker_headers():
    """A second, distinct baker identity for segregation-of-duties paths."""
    return TEST_USERS["second_baker_headers"]


@pytest.fixture
def decorator_headers():
    """PRD §2.1: the custom cake decorator (opaque identity)."""
    return TEST_USERS["decorator_headers"]


@pytest.fixture
def cake_desk_headers():
    """PRD §2.1: the front-counter cake desk operator (opaque identity)."""
    return TEST_USERS["cake_desk_headers"]


@pytest.fixture
def manager_headers_for():
    """Build ``DepartmentManager`` headers for a department id.

    PRD §2.1: when the role is ``DepartmentManager`` the ``X-User-ID`` header is
    the ``id`` of the acting ``BakeryDepartment``, so manager headers can only be
    built once the department exists.
    """
    return make_department_manager_headers
