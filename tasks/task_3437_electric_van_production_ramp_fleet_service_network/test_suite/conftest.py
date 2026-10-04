"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is managed externally; every test runs against a
freshly restarted, empty server. These fixtures only bridge test_helpers
objects into pytest's fixture namespace.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle managed externally)."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def charging_coordinator_headers():
    return TEST_USERS["charging_coordinator_headers"]


@pytest.fixture
def fleet_manager_headers():
    """Shared FleetManager headers — non-ownership assertions only.

    FleetManager is entity-backed: ownership-gated calls must build headers
    with make_fleet_manager_headers(customer["id"]) instead.
    """
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def service_dispatcher_headers():
    return TEST_USERS["service_dispatcher_headers"]


@pytest.fixture
def service_technician_headers():
    return TEST_USERS["service_technician_headers"]


@pytest.fixture
def service_technician_alt_headers():
    return TEST_USERS["service_technician_alt_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def release_manager_headers():
    return TEST_USERS["release_manager_headers"]


@pytest.fixture
def telematics_ingestion_headers():
    return TEST_USERS["telematics_ingestion_headers"]
