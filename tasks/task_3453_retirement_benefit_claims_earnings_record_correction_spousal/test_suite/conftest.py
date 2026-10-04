"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def employer_headers():
    return TEST_USERS["employer_headers"]


@pytest.fixture
def claims_specialist_headers():
    return TEST_USERS["claims_specialist_headers"]


@pytest.fixture
def senior_adjudicator_headers():
    return TEST_USERS["senior_adjudicator_headers"]


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]
