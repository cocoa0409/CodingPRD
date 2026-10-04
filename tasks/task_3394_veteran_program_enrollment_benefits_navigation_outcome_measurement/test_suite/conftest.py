"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def accredited_representative_headers():
    return TEST_USERS["accredited_representative_headers"]


@pytest.fixture
def benefits_officer_headers():
    return TEST_USERS["benefits_officer_headers"]


@pytest.fixture
def career_counselor_headers():
    return TEST_USERS["career_counselor_headers"]


@pytest.fixture
def event_coordinator_headers():
    return TEST_USERS["event_coordinator_headers"]


@pytest.fixture
def outcome_analyst_headers():
    return TEST_USERS["outcome_analyst_headers"]
