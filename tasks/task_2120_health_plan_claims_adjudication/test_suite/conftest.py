"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def network_manager_headers():
    return TEST_USERS["network_manager_headers"]


@pytest.fixture
def claims_intake_headers():
    return TEST_USERS["claims_intake_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def utilization_reviewer_headers():
    return TEST_USERS["utilization_reviewer_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def provider_rep_headers():
    return TEST_USERS["provider_rep_headers"]
