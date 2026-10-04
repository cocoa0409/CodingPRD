"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle and PYTHONPATH are the runner's responsibility; this file
only bridges the helpers into pytest's fixture graph.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def care_advocate_headers():
    return TEST_USERS["care_advocate_headers"]


@pytest.fixture
def clinic_coordinator_headers():
    return TEST_USERS["clinic_coordinator_headers"]


@pytest.fixture
def clinical_reviewer_headers():
    return TEST_USERS["clinical_reviewer_headers"]


@pytest.fixture
def specialty_pharmacist_headers():
    return TEST_USERS["specialty_pharmacist_headers"]


@pytest.fixture
def claims_processor_headers():
    return TEST_USERS["claims_processor_headers"]


@pytest.fixture
def claims_reviewer_headers():
    return TEST_USERS["claims_reviewer_headers"]


@pytest.fixture
def network_manager_headers():
    return TEST_USERS["network_manager_headers"]


@pytest.fixture
def plan_administrator_headers():
    return TEST_USERS["plan_administrator_headers"]