"""Pytest fixtures exposing the Furniture Bank test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_case_manager_headers,
    make_volunteer_headers,
    make_warehouse_lead_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def dispatch_planner_headers():
    return TEST_USERS["dispatch_planner_headers"]


@pytest.fixture
def warehouse_lead_headers():
    return TEST_USERS["warehouse_lead_headers"]


@pytest.fixture
def warehouse_releaser_headers():
    return TEST_USERS["warehouse_releaser_headers"]


@pytest.fixture
def case_manager_headers():
    """Shared CaseManager constant. Only safe for calls that never reach an
    ownership comparison; scoped calls must use make_case_manager_headers()."""
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def volunteer_headers():
    """Shared Volunteer constant. Only safe for calls that never reach a
    self-scoping comparison; scoped calls must use make_volunteer_headers()."""
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def case_manager_for():
    """Builder: returns CaseManager headers bound to a real PartnerAgency id."""
    return make_case_manager_headers


@pytest.fixture
def volunteer_for():
    """Builder: returns Volunteer headers bound to a real Volunteer row id."""
    return make_volunteer_headers


@pytest.fixture
def warehouse_lead_for():
    """Builder: returns WarehouseLead headers bound to an opaque operator id."""
    return make_warehouse_lead_headers
