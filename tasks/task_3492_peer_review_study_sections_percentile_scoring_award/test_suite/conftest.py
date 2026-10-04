"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; these fixtures
only bridge test_helpers into the pytest fixture namespace. Tests may equally
import the helpers directly at module level.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Shared API client. Server lifecycle managed by the runner."""
    return api_client.get_default_client()


@pytest.fixture
def program_officer_headers() -> dict:
    return TEST_USERS["program_officer_headers"]


@pytest.fixture
def referral_officer_headers() -> dict:
    return TEST_USERS["referral_officer_headers"]


@pytest.fixture
def sro_headers() -> dict:
    return TEST_USERS["sro_headers"]


@pytest.fixture
def council_member_headers() -> dict:
    return TEST_USERS["council_member_headers"]


@pytest.fixture
def grants_officer_headers() -> dict:
    return TEST_USERS["grants_officer_headers"]


@pytest.fixture
def applicant_headers() -> dict:
    """Fallback Applicant headers for tests that never exercise ownership."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def reviewer_headers() -> dict:
    """Fallback Reviewer headers for tests that never exercise ownership."""
    return TEST_USERS["reviewer_headers"]
