"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def receiving_tech_headers():
    return TEST_USERS["receiving_tech_headers"]


@pytest.fixture
def receiving_tech_2_headers():
    return TEST_USERS["receiving_tech_2_headers"]


@pytest.fixture
def inventory_lead_headers():
    return TEST_USERS["inventory_lead_headers"]


@pytest.fixture
def inventory_lead_2_headers():
    return TEST_USERS["inventory_lead_2_headers"]


@pytest.fixture
def circ_clinician_headers():
    return TEST_USERS["circ_clinician_headers"]


@pytest.fixture
def circ_clinician_2_headers():
    return TEST_USERS["circ_clinician_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def revenue_analyst_headers():
    return TEST_USERS["revenue_analyst_headers"]


@pytest.fixture
def revenue_analyst_2_headers():
    return TEST_USERS["revenue_analyst_2_headers"]
