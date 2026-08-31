"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    OFFICER_ALICE,
    OFFICER_BOB,
    TEST_USERS,
    ApiClient,
    api_client,
    make_compliance_officer_headers,
    no_auth_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["project_admin_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["wellfield_technician_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["commercial_scheduler_headers"]


@pytest.fixture
def officer_headers():
    """The preparing compliance officer."""
    return make_compliance_officer_headers(OFFICER_ALICE)


@pytest.fixture
def reviewer_headers():
    """A second compliance officer, so segregation of duties can be satisfied."""
    return make_compliance_officer_headers(OFFICER_BOB)


@pytest.fixture
def host_representative_headers():
    """Shared constant — safe only where no ownership check is reached."""
    return TEST_USERS["host_representative_headers"]


@pytest.fixture
def offtaker_headers():
    """Shared constant — safe only where no ownership check is reached."""
    return TEST_USERS["offtaker_headers"]


@pytest.fixture
def anonymous_headers():
    return no_auth_headers()
