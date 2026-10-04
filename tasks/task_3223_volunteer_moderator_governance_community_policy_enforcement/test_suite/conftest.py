"""Pytest fixtures exposing the generated helper infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def account_headers():
    return TEST_USERS["account_headers"]


@pytest.fixture
def moderator_headers():
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def content_reviewer_headers():
    return TEST_USERS["content_reviewer_headers"]


@pytest.fixture
def succession_auditor_headers():
    return TEST_USERS["succession_auditor_headers"]