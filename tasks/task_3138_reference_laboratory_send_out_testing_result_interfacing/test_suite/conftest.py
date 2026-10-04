"""Pytest fixtures exposing the send-out testing helpers.

Server lifecycle is owned by prd-bench-local-runner: the API process is killed
and relaunched before every individual test, so each test starts against an
empty database. Nothing here starts, stops or health-checks the server.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """Session-scoped API client pointed at API_BASE_URL."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["reference_lab_operations_headers"]


@pytest.fixture
def client_admin_headers():
    return TEST_USERS["lab_client_admin_headers"]


@pytest.fixture
def courier_headers():
    return TEST_USERS["courier_coordinator_headers"]


@pytest.fixture
def accessioning_headers():
    return TEST_USERS["accessioning_technologist_headers"]


@pytest.fixture
def medtech_headers():
    return TEST_USERS["medical_technologist_headers"]


@pytest.fixture
def interface_headers():
    return TEST_USERS["interface_analyst_headers"]


@pytest.fixture
def pathologist_headers():
    return TEST_USERS["pathologist_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["lab_billing_specialist_headers"]


@pytest.fixture
def utilization_headers():
    return TEST_USERS["utilization_reviewer_headers"]