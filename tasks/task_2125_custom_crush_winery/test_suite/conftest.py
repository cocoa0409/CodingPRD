"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def cellar_supervisor_headers():
    return TEST_USERS["cellar_supervisor_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def client_rep_headers():
    return TEST_USERS["client_rep_headers"]
