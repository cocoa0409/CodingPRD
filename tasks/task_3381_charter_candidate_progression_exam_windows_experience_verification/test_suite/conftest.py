"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def experience_reviewer_headers():
    return TEST_USERS["experience_reviewer_headers"]


@pytest.fixture
def reference_provider_headers():
    return TEST_USERS["reference_provider_headers"]


@pytest.fixture
def conduct_investigator_headers():
    return TEST_USERS["conduct_investigator_headers"]


@pytest.fixture
def conduct_adjudicator_headers():
    return TEST_USERS["conduct_adjudicator_headers"]
