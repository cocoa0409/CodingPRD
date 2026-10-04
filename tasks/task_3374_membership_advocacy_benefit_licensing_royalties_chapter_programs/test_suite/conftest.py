"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def member_services_headers():
    return TEST_USERS["member_services_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def provider_manager_headers():
    return TEST_USERS["provider_manager_headers"]


@pytest.fixture
def governance_officer_headers():
    return TEST_USERS["governance_officer_headers"]


@pytest.fixture
def oversight_analyst_headers():
    return TEST_USERS["oversight_analyst_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def standards_reviewer_headers():
    return TEST_USERS["standards_reviewer_headers"]


@pytest.fixture
def chapter_coordinator_headers():
    return TEST_USERS["chapter_coordinator_headers"]


@pytest.fixture
def advocacy_director_headers():
    return TEST_USERS["advocacy_director_headers"]
