"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def issuer_officer_headers():
    return TEST_USERS["issuer_officer_headers"]


@pytest.fixture
def listing_analyst_headers():
    return TEST_USERS["listing_analyst_headers"]


@pytest.fixture
def hearings_officer_headers():
    return TEST_USERS["hearings_officer_headers"]


@pytest.fixture
def listings_council_headers():
    return TEST_USERS["listings_council_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]
