"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def triage_nurse_headers():
    return TEST_USERS["triage_nurse_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def care_team_member_headers():
    return TEST_USERS["care_team_member_headers"]


@pytest.fixture
def app_headers():
    return TEST_USERS["app_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def supervising_physician_headers():
    return TEST_USERS["supervising_physician_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def payer_adjudicator_headers():
    return TEST_USERS["payer_adjudicator_headers"]
