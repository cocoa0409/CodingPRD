"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def intake_coordinator_b_headers():
    return TEST_USERS["intake_coordinator_b_headers"]


@pytest.fixture
def case_reviewer_headers():
    return TEST_USERS["case_reviewer_headers"]


@pytest.fixture
def financial_counselor_headers():
    return TEST_USERS["financial_counselor_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]
