"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def talent_agent_headers():
    return TEST_USERS["talent_agent_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def reviewing_officer_headers():
    return TEST_USERS["reviewing_officer_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def brand_rep_headers():
    """Shared BrandRep identity — only safe where no ownership check runs."""
    return TEST_USERS["brand_rep_headers"]


@pytest.fixture
def athlete_headers():
    """Shared Athlete identity — only safe where no ownership check runs."""
    return TEST_USERS["athlete_headers"]


@pytest.fixture
def no_auth_headers():
    return TEST_USERS["no_auth_headers"]
