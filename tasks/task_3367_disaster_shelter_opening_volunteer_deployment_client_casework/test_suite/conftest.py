"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so every test starts
against an empty database and must build its own preconditions.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["national_hq_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["regional_coordinator_headers"]


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def second_finance_headers():
    return TEST_USERS["second_finance_officer_headers"]


@pytest.fixture
def blood_headers():
    return TEST_USERS["blood_services_coordinator_headers"]


@pytest.fixture
def shelter_manager_headers():
    """Fallback ShelterManager identity, safe only for non-ownership calls."""
    return TEST_USERS["shelter_manager_headers"]


@pytest.fixture
def volunteer_headers():
    """Fallback Volunteer identity, safe only for non-ownership calls."""
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def client_headers():
    """Fallback Client identity, safe only for non-ownership calls."""
    return TEST_USERS["client_headers"]
