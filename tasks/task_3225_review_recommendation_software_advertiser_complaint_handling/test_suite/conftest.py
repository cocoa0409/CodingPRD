"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]


@pytest.fixture
def content_moderator_headers():
    return TEST_USERS["content_moderator_headers"]


@pytest.fixture
def trust_investigator_headers():
    return TEST_USERS["trust_investigator_headers"]


@pytest.fixture
def support_admin_headers():
    return TEST_USERS["support_admin_headers"]


@pytest.fixture
def legal_ops_headers():
    return TEST_USERS["legal_ops_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def business_owner_headers():
    return TEST_USERS["business_owner_headers"]


@pytest.fixture
def advertiser_headers():
    return TEST_USERS["advertiser_headers"]


@pytest.fixture
def reporter_headers():
    return TEST_USERS["reporter_headers"]
