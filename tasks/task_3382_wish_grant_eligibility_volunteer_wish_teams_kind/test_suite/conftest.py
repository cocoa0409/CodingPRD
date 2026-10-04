"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the API server before every test and injects
API_BASE_URL; these fixtures only bridge test_helpers into pytest's
fixture namespace. Tests may equally well import helpers directly.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def national_admin_headers():
    return TEST_USERS["national_admin_headers"]


@pytest.fixture
def referral_source_headers():
    return TEST_USERS["referral_source_headers"]


@pytest.fixture
def medical_provider_headers():
    return TEST_USERS["medical_provider_headers"]


@pytest.fixture
def eligibility_reviewer_headers():
    return TEST_USERS["eligibility_reviewer_headers"]


@pytest.fixture
def volunteer_headers():
    # Fallback identity only; membership-gated calls must build headers from
    # the real volunteer entity id via make_volunteer_headers().
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def wish_coordinator_headers():
    return TEST_USERS["wish_coordinator_headers"]


@pytest.fixture
def in_kind_officer_headers():
    return TEST_USERS["in_kind_officer_headers"]


@pytest.fixture
def chapter_director_headers():
    return TEST_USERS["chapter_director_headers"]


@pytest.fixture
def chapter_director_alt_headers():
    return TEST_USERS["chapter_director_alt_headers"]


@pytest.fixture
def national_director_headers():
    return TEST_USERS["national_director_headers"]
