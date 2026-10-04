"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def reviewer1_headers():
    return TEST_USERS["reviewer1_headers"]


@pytest.fixture
def reviewer2_headers():
    return TEST_USERS["reviewer2_headers"]


@pytest.fixture
def reviewer3_headers():
    return TEST_USERS["reviewer3_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def care_headers():
    return TEST_USERS["care_headers"]


@pytest.fixture
def outreach_headers():
    return TEST_USERS["outreach_headers"]


@pytest.fixture
def philanthropy_headers():
    return TEST_USERS["philanthropy_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]
