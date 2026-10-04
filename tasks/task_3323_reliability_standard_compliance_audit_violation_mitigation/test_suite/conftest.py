"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def registration_coordinator_headers():
    return TEST_USERS["registration_coordinator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def regional_reviewer_headers():
    return TEST_USERS["regional_reviewer_headers"]


@pytest.fixture
def federal_reviewer_headers():
    return TEST_USERS["federal_reviewer_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def cip_manager_headers():
    return TEST_USERS["cip_manager_headers"]
