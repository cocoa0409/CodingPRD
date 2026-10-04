"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["claim_adjudicator_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["trade_in_inspector_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]