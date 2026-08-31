"""Pytest fixtures exposing the care-management test helpers."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def utilization_analyst_headers():
    return TEST_USERS["utilization_analyst_headers"]


@pytest.fixture
def care_manager_headers():
    return TEST_USERS["care_manager_headers"]


@pytest.fixture
def clinical_reviewer_headers():
    return TEST_USERS["clinical_reviewer_headers"]


@pytest.fixture
def community_partner_headers():
    return TEST_USERS["community_partner_headers"]
