"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle and PYTHONPATH are managed by prd-bench-local-runner; the
server is restarted before every test, so each test starts against an empty
database and must build its own preconditions.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle managed by the runner)."""
    return api_client


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def corridor_manager_headers():
    return TEST_USERS["corridor_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def carrier_dispatcher_headers():
    return TEST_USERS["carrier_dispatcher_headers"]


@pytest.fixture
def terminal_manager_headers():
    return TEST_USERS["terminal_manager_headers"]


@pytest.fixture
def remote_support_supervisor_headers():
    return TEST_USERS["remote_support_supervisor_headers"]


@pytest.fixture
def remote_support_operator_headers():
    return TEST_USERS["remote_support_operator_headers"]


@pytest.fixture
def incident_reviewer_headers():
    return TEST_USERS["incident_reviewer_headers"]


@pytest.fixture
def safety_case_author_headers():
    return TEST_USERS["safety_case_author_headers"]


@pytest.fixture
def regulatory_liaison_headers():
    return TEST_USERS["regulatory_liaison_headers"]


@pytest.fixture
def fleet_maintenance_tech_headers():
    return TEST_USERS["fleet_maintenance_tech_headers"]


@pytest.fixture
def driver_outreach_headers():
    return TEST_USERS["driver_outreach_headers"]


@pytest.fixture
def shipper_partnership_headers():
    return TEST_USERS["shipper_partnership_headers"]


@pytest.fixture
def booking_clerk_headers():
    return TEST_USERS["booking_clerk_headers"]


@pytest.fixture
def terminal_operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def exchange_participant_headers():
    return TEST_USERS["exchange_participant_headers"]