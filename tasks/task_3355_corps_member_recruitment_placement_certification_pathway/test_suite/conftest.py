"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


# ─── One fixture per role ─────────────────────────────

@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def selection_manager_headers():
    return TEST_USERS["selection_manager_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant headers; ownership-gated calls build their own."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def placement_coordinator_headers():
    return TEST_USERS["placement_coordinator_headers"]


@pytest.fixture
def institute_director_headers():
    return TEST_USERS["institute_director_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]
