"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst2_headers():
    return TEST_USERS["analyst2_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def appraiser2_headers():
    return TEST_USERS["appraiser2_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def reg_officer_headers():
    return TEST_USERS["reg_officer_headers"]


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def transition_mgr_headers():
    return TEST_USERS["transition_mgr_headers"]


@pytest.fixture
def hr_headers():
    return TEST_USERS["hr_headers"]


@pytest.fixture
def sysadmin_headers():
    return TEST_USERS["sysadmin_headers"]
