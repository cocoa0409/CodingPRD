"""Pytest fixtures exposing the shared test infrastructure.

The server is restarted against an empty database before every individual test,
so nothing here is stateful: the session-scoped client is a bare HTTP wrapper and
every precondition a test needs is rebuilt through the API inside that test.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""

    return api_client


# ---------------------------------------------------------------------------
# One fixture per named individual. Segregation of duties is enforced on
# X-User-ID rather than on the role, so several distinct people share a role.
# ---------------------------------------------------------------------------


@pytest.fixture
def engineer_headers():
    return TEST_USERS["route_engineer"]


@pytest.fixture
def engineer_alt_headers():
    return TEST_USERS["route_engineer_second"]


@pytest.fixture
def engineer_third_headers():
    return TEST_USERS["route_engineer_third"]


@pytest.fixture
def engineer_fourth_headers():
    return TEST_USERS["route_engineer_fourth"]


@pytest.fixture
def surveyor_headers():
    return TEST_USERS["field_surveyor"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["permit_coordinator"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["authority_reviewer"]


@pytest.fixture
def reviewer_alt_headers():
    return TEST_USERS["authority_reviewer_second"]


@pytest.fixture
def rail_reviewer_headers():
    return TEST_USERS["authority_reviewer_rail"]


@pytest.fixture
def highway_reviewer_headers():
    return TEST_USERS["authority_reviewer_highway"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["pole_owner"]


@pytest.fixture
def owner_alt_headers():
    return TEST_USERS["pole_owner_second"]


@pytest.fixture
def owner_municipal_headers():
    return TEST_USERS["pole_owner_municipal"]


@pytest.fixture
def owner_electric_headers():
    return TEST_USERS["pole_owner_electric"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["network_records_admin"]
