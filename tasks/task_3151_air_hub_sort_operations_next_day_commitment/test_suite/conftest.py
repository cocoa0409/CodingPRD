"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def hub_ops_manager_headers():
    return TEST_USERS["hub_ops_manager_headers"]


@pytest.fixture
def sort_supervisor_headers():
    return TEST_USERS["sort_supervisor_headers"]


@pytest.fixture
def sort_operator_headers():
    return TEST_USERS["sort_operator_headers"]


@pytest.fixture
def load_planner_headers():
    return TEST_USERS["load_planner_headers"]


@pytest.fixture
def commitment_controller_headers():
    return TEST_USERS["commitment_controller_headers"]


@pytest.fixture
def feeder_coordinator_headers():
    return TEST_USERS["feeder_coordinator_headers"]


@pytest.fixture
def gateway_coordinator_headers():
    return TEST_USERS["gateway_coordinator_headers"]


@pytest.fixture
def hazmat_certifier_headers():
    return TEST_USERS["hazmat_certifier_headers"]


@pytest.fixture
def weather_officer_headers():
    return TEST_USERS["weather_officer_headers"]


@pytest.fixture
def refund_adjuster_headers():
    return TEST_USERS["refund_adjuster_headers"]