"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def network_operator_headers():
    return TEST_USERS["network_operator_headers"]


@pytest.fixture
def enrollment_coordinator_headers():
    return TEST_USERS["enrollment_coordinator_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def transport_dispatcher_headers():
    return TEST_USERS["transport_dispatcher_headers"]


@pytest.fixture
def triage_nurse_headers():
    return TEST_USERS["triage_nurse_headers"]


@pytest.fixture
def claims_adjudicator_headers():
    return TEST_USERS["claims_adjudicator_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]
