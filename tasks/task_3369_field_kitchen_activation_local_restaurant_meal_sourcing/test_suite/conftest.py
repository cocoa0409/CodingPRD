"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_kitchen_operator_headers,
    make_site_coordinator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["field_coordinator_headers"]


@pytest.fixture
def safety_headers():
    return TEST_USERS["food_safety_officer_headers"]


@pytest.fixture
def partnership_headers():
    return TEST_USERS["partnership_lead_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def sourcing_headers():
    return TEST_USERS["sourcing_officer_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def donor_headers():
    return TEST_USERS["donor_liaison_headers"]


@pytest.fixture
def kitchen_operator_headers():
    """Non-ownership fallback for the entity-backed KitchenOperator role."""
    return TEST_USERS["kitchen_operator_headers"]


@pytest.fixture
def site_coordinator_headers():
    """Non-ownership fallback for the entity-backed SiteCoordinator role."""
    return TEST_USERS["site_coordinator_headers"]


@pytest.fixture
def operator_headers():
    """Builder for ownership-gated KitchenOperator calls."""
    return make_kitchen_operator_headers


@pytest.fixture
def site_owner_headers():
    """Builder for ownership-gated SiteCoordinator calls."""
    return make_site_coordinator_headers
