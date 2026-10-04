"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["implementation_director_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["implementation_analyst_headers"]


@pytest.fixture
def build_analyst_headers():
    return TEST_USERS["build_analyst_headers"]


@pytest.fixture
def test_lead_headers():
    return TEST_USERS["test_lead_headers"]


@pytest.fixture
def training_headers():
    return TEST_USERS["training_coordinator_headers"]


@pytest.fixture
def conversion_headers():
    return TEST_USERS["conversion_analyst_headers"]


@pytest.fixture
def reconciler_headers():
    return TEST_USERS["order_reconciler_headers"]


@pytest.fixture
def revenue_headers():
    return TEST_USERS["revenue_cycle_analyst_headers"]


@pytest.fixture
def interface_headers():
    return TEST_USERS["interface_engineer_headers"]


@pytest.fixture
def cutover_headers():
    return TEST_USERS["cutover_lead_headers"]


@pytest.fixture
def command_center_headers():
    return TEST_USERS["command_center_lead_headers"]


@pytest.fixture
def triage_headers():
    return TEST_USERS["triage_commander_headers"]


@pytest.fixture
def optimization_headers():
    return TEST_USERS["optimization_lead_headers"]